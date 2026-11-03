"""共享检索核心：分块、建索引、混合召回、重排、Prompt 组装、权限过滤。

stage1/stage2/stage3 里各自有一份实现，这里抽出来给评测脚本和服务复用。
"""
import glob
import os
import re
import time
import hashlib
import logging

import chromadb
import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

HERE = os.path.dirname(os.path.abspath(__file__))
EMB_MODEL = "BAAI/bge-small-zh-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"
CANDIDATES = 10
logger = logging.getLogger("rag.core")


# 语料目录支持用环境变量切换：RAG_CORPUS_DIR=corpus_real
def corpus_dir():
    d = os.getenv("RAG_CORPUS_DIR", "corpus")
    return d if os.path.isabs(d) else os.path.join(HERE, d)


PROMPT_TMPL = """你是企业知识库助手。请只依据下面的【资料】回答问题。

规则：
1. 资料里有答案就简洁回答，并在句末标注引用编号，例如 [1][2]。
2. 资料里没有答案，就回答“根据现有资料无法回答”，不要编造。
3. 不要使用资料以外的知识。
4. 可以对资料中的数字做简单加减乘除。

【资料】
{context}

【问题】{question}
"""


def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def chunk_text(text, max_chars=320, overlap=40):
    blocks = [b.strip() for b in re.split(r"(?m)^(?=#{1,3}\s)", text.strip()) if b.strip()]
    chunks = []
    for b in blocks:
        if len(b) <= max_chars:
            chunks.append(b)
            continue
        start = 0
        while start < len(b):
            chunks.append(b[start:start + max_chars])
            if start + max_chars >= len(b):
                break
            start += max_chars - overlap
    return [c for c in chunks if len(c.strip()) > 20]


def load_corpus():
    texts, metas = [], []
    for path in sorted(glob.glob(os.path.join(corpus_dir(), "*.md"))):
        raw = open(path, encoding="utf-8").read()
        name = os.path.basename(path)
        for i, ch in enumerate(chunk_text(raw)):
            texts.append(ch)
            metas.append(f"{name}#{i}")
    return texts, metas


def rrf(rank_lists, k=60):
    scores = {}
    for ranking in rank_lists:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return [i for i, _ in sorted(scores.items(), key=lambda x: -x[1])]


def build_prompt(question, hits):
    ctx = "\n\n".join(f"[{i+1}] 来源：{src}\n{text}" for i, (src, text) in enumerate(hits))
    return PROMPT_TMPL.format(context=ctx, question=question)


# ---------- 权限模型（演示用） ----------
# 真实系统里 ACL 来自文档管理系统；这里按文件名关键词做确定性分配，
# 保证同一篇文档每次启动的归属一致，方便复现和演示。
ACL_RULES = [
    (("计费", "订阅", "价格", "发票"), "财务", 2),
    (("教程", "课程", "快速入门"), "全员", 0),
    (("插件", "API", "CLI", "MCP", "Webhook", "密钥", "标注"), "研发", 1),
]


def acl_for(filename):
    """返回 (部门, 密级)：0=公开，1=内部，2=机密。"""
    for keys, dept, level in ACL_RULES:
        if any(k in filename for k in keys):
            return dept, level
    return "产品", 1


class KnowledgeBase:
    def __init__(self):
        # 两个模型只加载一次，refresh/reload 复用
        self.embedder = SentenceTransformer(EMB_MODEL)
        self.reranker = CrossEncoder(RERANK_MODEL, max_length=512)
        # chromadb 的 EphemeralClient 在进程内共享，必须复用同一个实例
        self._client = chromadb.EphemeralClient()
        self._build_index()

    # ---------- 建索引 ----------
    def _build_index(self):
        self.chunks, self.metas = load_corpus()
        cache_dir = os.path.abspath(os.path.join(os.path.dirname(HERE), "..", "work", "emb_cache"))
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, self._fingerprint() + ".npy")
        emb = None
        if os.path.exists(cache_file):
            emb = np.load(cache_file)
            if emb.shape[0] != len(self.chunks):
                emb = None
            else:
                logger.info("命中 embedding 缓存：%d 条", len(self.chunks))
        if emb is None:
            logger.info("计算 embedding：%d 条，首次会慢一些", len(self.chunks))
            emb = self.embedder.encode(self.chunks, normalize_embeddings=True,
                                        show_progress_bar=False)
            np.save(cache_file, emb)
        self.emb = emb
        self._sync_maps()
        # 分词结果缓存下来，增量更新时只需给新片段分词
        self.tokens = [list(jieba.cut(c)) for c in self.chunks]
        self._rebuild_collection()
        self._rebuild_bm25()
        self._file_sig = self._file_signature()
        self.built_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def _apply_acl(self):
        """按文件名给每个 chunk 打上部门和密级。"""
        self.chunk_dept, self.chunk_level = [], []
        for m in self.metas:
            d, l = acl_for(m.split("#")[0])
            self.chunk_dept.append(d)
            self.chunk_level.append(l)

    def _sync_maps(self):
        """重建 id->下标 映射并刷新 ACL；增删片段后下标会变，必须同步。"""
        self.id_to_idx = {m: i for i, m in enumerate(self.metas)}
        self._apply_acl()

    def _metadatas(self):
        return [{"src": m, "file": m.split("#")[0], "dept": d, "level": l}
                for m, d, l in zip(self.metas, self.chunk_dept, self.chunk_level)]

    def _rebuild_collection(self):
        """只用内存里的向量重建向量库，不重新算 embedding。"""
        try:
            self._client.delete_collection("knowledge_base")
        except Exception:
            pass
        self.col = self._client.create_collection("knowledge_base", metadata={"hnsw:space": "cosine"})
        # 用片段的 meta 当 id（如 001_x.md#3），唯一且便于按文件删除
        ids = list(self.metas)
        metas = self._metadatas()
        # chromadb 单次写入上限 5461，大语料必须分批
        for start in range(0, len(self.chunks), 1000):
            end = start + 1000
            self.col.add(ids=ids[start:end],
                         documents=self.chunks[start:end],
                         embeddings=[e.tolist() for e in self.emb[start:end]],
                         metadatas=metas[start:end])

    def _rebuild_bm25(self):
        self.bm25 = BM25Okapi(self.tokens)

    # ---------- 权限 ----------
    def _visible_mask(self, dept=None, clearance=None):
        """返回布尔数组，标记当前用户能看到哪些 chunk。"""
        if dept is None and clearance is None:
            return np.ones(len(self.chunks), dtype=bool)
        clr = 99 if clearance is None else int(clearance)
        mask = np.zeros(len(self.chunks), dtype=bool)
        for i, (d, l) in enumerate(zip(self.chunk_dept, self.chunk_level)):
            if l == 0:
                mask[i] = True                       # 公开文档所有人可见
            elif dept in (None, "", "全员"):
                mask[i] = l <= clr                   # 不限部门，只看密级
            else:
                mask[i] = (d == dept) and (l <= clr)  # 本部门且密级够
        return mask

    def _chroma_where(self, dept, clearance):
        """转成 chromadb 的 where 条件，必须在检索阶段过滤，不能检索后再筛。"""
        if dept is None and clearance is None:
            return None
        clr = 99 if clearance is None else int(clearance)
        level_clause = {"level": {"$lte": clr}}
        if dept in (None, "", "全员"):
            return level_clause
        return {"$or": [{"level": 0}, {"$and": [{"dept": dept}, level_clause]}]}

    # ---------- 检索 ----------
    def retrieve(self, query, k=3, candidates=None, dept=None, clearance=None):
        """返回 [(chunk_index, 来源, 文本, 重排分数), ...]，已按权限过滤。"""
        mask = self._visible_mask(dept, clearance)
        if not mask.any():
            return []
        where = self._chroma_where(dept, clearance)
        kwargs = {
            "query_embeddings": [self.embedder.encode(query, normalize_embeddings=True).tolist()],
            "n_results": int(mask.sum()),
        }
        if where is not None:
            kwargs["where"] = where
        ids = self.col.query(**kwargs)["ids"][0]
        # id 现在是 meta（如 001_x.md#3），用映射转回当前下标
        vec = [self.id_to_idx[x] for x in ids
               if x in self.id_to_idx and mask[self.id_to_idx[x]]]

        # BM25 也要过滤：先算全量分数，再把不可见的置为极小值
        bm_scores = self.bm25.get_scores(list(jieba.cut(query)))
        masked = np.where(mask, bm_scores, -1e9)
        bm = [int(i) for i in np.argsort(masked)[::-1] if mask[i]][:200]

        cand = rrf([vec, bm])[:(candidates or CANDIDATES)]
        if not cand:
            return []
        scores = self.reranker.predict([(query, self.chunks[i]) for i in cand],
                                       show_progress_bar=False)
        order = sorted(range(len(cand)), key=lambda j: -float(scores[j]))
        return [(cand[j], self.metas[cand[j]], self.chunks[cand[j]], float(scores[j]))
                for j in order[:k]]

    # ---------- 增量索引 ----------
    def _file_signature(self):
        sig = {}
        for path in glob.glob(os.path.join(corpus_dir(), "*.md")):
            name = os.path.basename(path)
            sig[name] = (os.path.getsize(path), int(os.path.getmtime(path)))
        return sig

    def incremental_update(self):
        """只重算新增/修改的文件，删除的文件从索引里摘掉。"""
        current = self._file_signature()
        old = getattr(self, "_file_sig", {})
        added = sorted(set(current) - set(old))
        changed = sorted(f for f in current if f in old and current[f] != old[f])
        deleted = sorted(set(old) - set(current))
        if not (added or changed or deleted):
            return {"added": [], "changed": [], "deleted": [],
                    "chunks": len(self.chunks), "unchanged": True}

        dirty = set(added) | set(changed)
        drop = dirty | set(deleted)
        keep = [i for i, m in enumerate(self.metas) if m.split("#")[0] not in drop]

        chunks = [self.chunks[i] for i in keep]
        metas = [self.metas[i] for i in keep]
        tokens = [self.tokens[i] for i in keep]
        emb = self.emb[keep] if keep else np.zeros((0, self.emb.shape[1]), dtype=self.emb.dtype)

        new_chunks, new_metas = [], []
        for f in sorted(dirty):
            raw = open(os.path.join(corpus_dir(), f), encoding="utf-8").read()
            for j, c in enumerate(chunk_text(raw)):
                new_chunks.append(c)
                new_metas.append(f"{f}#{j}")

        if new_chunks:
            new_emb = self.embedder.encode(new_chunks, normalize_embeddings=True,
                                           show_progress_bar=False)
            chunks += new_chunks
            metas += new_metas
            tokens += [list(jieba.cut(c)) for c in new_chunks]
            emb = np.vstack([emb, new_emb])

        self.chunks, self.metas, self.emb = chunks, metas, emb
        self.tokens = tokens
        self._sync_maps()

        # 向量库只处理变更：按文件删旧片段，再追加新片段，不做全量重写
        for f in sorted(drop):
            self.col.delete(where={"file": f})
        if new_chunks:
            self.col.add(ids=new_metas,
                         documents=new_chunks,
                         embeddings=[e.tolist() for e in new_emb],
                         metadatas=self._metadatas()[-len(new_chunks):])
        self._rebuild_bm25()
        self._file_sig = current
        self.built_at = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info("增量更新：新增 %s / 修改 %s / 删除 %s，现有 %d 片段",
                    added, changed, deleted, len(self.chunks))
        return {"added": added, "changed": changed, "deleted": deleted,
                "chunks": len(self.chunks), "unchanged": False}

    # ---------- 其他 ----------
    def reload(self):
        self._build_index()
        return len(self.chunks)

    def _fingerprint(self):
        h = hashlib.sha256()
        for path in sorted(glob.glob(os.path.join(corpus_dir(), "*.md"))):
            h.update(os.path.basename(path).encode())
            h.update(str(os.path.getsize(path)).encode())
            h.update(str(int(os.path.getmtime(path))).encode())
        return h.hexdigest()[:16]

    def gold_indices(self, needle):
        return {i for i, c in enumerate(self.chunks) if needle in c}

