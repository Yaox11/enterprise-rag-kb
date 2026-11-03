"""FastAPI 接口层：只做参数校验、调用服务、错误映射，不放业务逻辑。"""
import logging
import collections
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .service import RagService

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("rag.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时加载模型（阻塞操作放线程池，避免卡住事件循环）。"""
    logger.info("正在初始化 RAG 服务...")
    app.state.svc = await run_in_threadpool(RagService)
    logger.info("RAG 服务就绪")
    yield
    logger.info("RAG 服务关闭")


app = FastAPI(title="企业知识库问答 API", version="1.0.0", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    top_k: int = Field(3, ge=1, le=5, description="返回的引用片段数量")
    dept: str = Field("全员", description="部门，用于权限过滤")
    clearance: int = Field(1, ge=0, le=2, description="密级：0 公开 / 1 内部 / 2 机密")


class Citation(BaseModel):
    id: int
    source: str
    snippet: str
    score: float


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    latency_ms: int
    model: str
    cached: bool = False
    refused: bool = False
    top_score: float | None = None


@app.get("/health")
async def health():
    """健康检查：前端启动时会先探测这个接口。"""
    svc: RagService = app.state.svc
    return {
        "status": "ok",
        "chunks": len(svc.kb.chunks),
        "documents": len({m.split("#")[0] for m in svc.kb.metas}),
        "index_built_at": svc.kb.built_at,
        "model": svc.model,
        "llm_ready": svc.client is not None,
        "refusal_threshold": svc.refusal_threshold,
        "auth_enabled": bool(svc.tokens),
        "acl": dict(collections.Counter(svc.kb.chunk_dept)),
    }


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest,
              x_api_token: str | None = Header(default=None, alias="X-API-Token")):
    """问答主接口。阻塞的检索/生成放在线程池里执行。"""
    svc: RagService = app.state.svc

    # 配了 AUTH_TOKENS 就以 token 为准，请求体里的 dept/clearance 不再可信
    if svc.tokens:
        ident = svc.resolve_token(x_api_token)
        if ident is None:
            raise HTTPException(status_code=401, detail="无效或缺失的 API Token")
        dept, clearance = ident
    else:
        dept, clearance = req.dept, req.clearance

    try:
        # 权限参数一起传下去，在检索阶段就完成过滤
        data = await run_in_threadpool(svc.answer, req.question, req.top_k,
                                        dept, clearance)
        # 权限参数一起传下去，检索阶段就过滤
    except RuntimeError as exc:
        # 配置类问题（没写 key）返回 503，前端能给出可读提示
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        # 上游模型/网络异常返回 502
        logger.exception("问答处理失败")
        raise HTTPException(status_code=502, detail=f"上游模型错误：{exc}") from exc
    return data


@app.post("/reindex")
async def reindex():
    """重建索引。改完 corpus 里的文档后调用这个接口，不必重启服务。"""
    svc: RagService = app.state.svc
    result = await run_in_threadpool(svc.reindex)
    return {"status": "ok", **result}


@app.post("/refresh")
async def refresh():
    """增量更新：只重算改过的文件，不重建全库。"""
    svc: RagService = app.state.svc
    result = await run_in_threadpool(svc.refresh)
    return {"status": "ok", **result}

