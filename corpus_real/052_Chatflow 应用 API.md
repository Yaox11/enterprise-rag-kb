# Chatflow 应用 API

# Chatflow 应用 API

> Chatflow 应用 API，涵盖对话消息、工作流级别流式事件、会话管理、人工介入暂停

[Chatflow 应用](https://docs.dify.ai/zh/cloud/use-dify/build/workflow-chatflow.md) 运行在 `advanced-chat` 模式下，生成回复的同时流式传输工作流级别的事件（节点开始、完成、迭代、暂停）。之前的对话内容会保留为上下文，后续消息可引用更早的内容。

> [!NOTE]
>
> 认证方式、基础 URL，以及按终端用户区分数据的 `user` 字段，详见 [快速开始](https://docs.dify.ai/zh/api-reference/guides/get-started.md) 和 [终端用户身份](https://docs.dify.ai/zh/api-reference/guides/end-user-identity.md)。

## 发送消息并接收流式回复

* **[发送对话消息](https://docs.dify.ai/zh/api-reference/chat-messages/send-chat-message.md)**：向 Chatflow 应用发送用户提问。流式返回时，回复文本之外还会携带工作流和节点事件；阻塞式返回时，运行结束后才返回结果。
* **[停止响应](https://docs.dify.ai/zh/api-reference/chat-messages/stop-chat-message-generation.md)**：在回复完成前中断流式输出。
* **[获取下一轮建议问题列表](https://docs.dify.ai/zh/api-reference/chat-messages/get-next-suggested-questions.md)**：回复完成后，基于当前对话内容推荐后续问题。

## 管理会话

* **[获取会话列表](https://docs.dify.ai/zh/api-reference/conversations/list-conversations.md)**：按最近活跃时间排序，返回当前用户的会话。
* **[获取会话历史消息](https://docs.dify.ai/zh/api-reference/conversations/list-conversation-messages.md)**：返回某个会话的历史消息，适合滚动加载的聊天界面。
* **[重命名会话](https://docs.dify.ai/zh/api-reference/conversations/rename-conversation.md)**：设置或自动生成会话名称。
* **[删除会话](https://docs.dify.ai/zh/api-reference/conversations/delete-conversation.md)**：删除指定会话。
* **[获取会话变量](https://docs.dify.ai/zh/api-reference/conversations/list-conversation-variables.md)**：读取会话在多轮对话间保留的变量值。
* **[更新会话变量](https://docs.dify.ai/zh/api-reference/conversations/update-conversation-variable.md)**：直接修改其中某个变量的值。

## 处理文件

* **[上传文件](https://docs.dify.ai/zh/api-reference/files/upload-file.md)**：上传图片、文档、音频或视频文件，供 [发送对话消息](https://docs.dify.ai/zh/api-reference/chat-messages/send-chat-message.md) 引用。文件仅限上传的终端用户使用。
* **[下载文件](https://docs.dify.ai/zh/api-reference/files/download-file.md)**：预览或下载已上传的文件，前提是该文件属于当前应用内的某条消息。
* **[获取终端用户信息](https://docs.dify.ai/zh/api-reference/end-users/get-end-user-info.md)**：根据终端用户 ID（例如上传文件响应中的 `created_by`）查询该用户的详细信息。

## 语音转写与合成

* **[语音转文字](https://docs.dify.ai/zh/api-reference/audio/convert-audio-to-text.md)**：将上传的音频文件（MP3、M4A、WAV、AMR 或 MPGA，最大 30 MB）转写为文字，让终端用户用语音代替打字输入。
* **[文字转语音](https://docs.dify.ai/zh/api-reference/audio/convert-text-to-audio.md)**：将回复合成为语音。

## 人工介入暂停

当运行到达提交方式为 Web 应用的 [人工介入](https://docs.dify.ai/zh/cloud/use-dify/nodes/human-input) 节点时，可通过 API 完成这次暂停的处理：

**1. 监听暂停事件**

事件流会推送 `human_input_required` 事件，其中携带 `form_token` 和本次运行的 `workflow_run_id`，随后以 `workflow_paused` 事件结束。

**2. 获取表单**

使用 `form_token` 调用 [获取人工介入表单](https://docs.dify.ai/zh/api-reference/human-input/get-human-input-form.md)，加载表单内容。

**3. 提交填写结果**

通过 [提交人工介入表单](https://docs.dify.ai/zh/api-reference/human-input/submit-human-input-form.md) 发送接收者的填写内容。提交后运行恢复执行。

**4. 继续跟踪事件流**

使用暂停时事件流中的 `workflow_run_id`，调用 [流式获取工作流事件](https://docs.dify.ai/zh/api-reference/workflow-runs/stream-workflow-events.md) 打开新的事件流，跟踪剩余事件，直到最终回复。

带文件的表单提交与完整事件序列，详见 [人工介入流程](https://docs.dify.ai/zh/api-reference/guides/human-input-flow.md) 指南。

## 查看工作流运行

* **[获取工作流执行情况](https://docs.dify.ai/zh/api-reference/workflow-runs/get-workflow-run-detail.md)**：根据 `workflow_run_id` 查询某次运行的状态与输出，该 ID 出现在对话回复附带的工作流和节点事件中。
* **[获取工作流日志](https://docs.dify.ai/zh/api-reference/workflow-runs/list-workflow-logs.md)**：返回运行级别的汇总信息（状态、token 用量、步骤数、耗时），而非逐节点的执行日志。

## 获取应用信息与配置

* **[获取应用基本信息](https://docs.dify.ai/zh/api-reference/applications/get-app-info.md)**：返回应用的名称、描述、标签和模式。
* **[获取应用参数](https://docs.dify.ai/zh/api-reference/applications/get-app-parameters.md)**：返回调用需在 `inputs` 中传入的字段（名称、类型、默认值），以及应用的功能开关，可据此构建请求或客户端界面。
* **[获取应用元数据](https://docs.dify.ai/zh/api-reference/applications/get-app-meta.md)**：返回工具图标等配置元数据。
* **[获取应用 Web 应用设置](https://docs.dify.ai/zh/api-reference/applications/get-app-webapp-settings.md)**：返回 Web 应用的站点配置、主题和自定义选项。

## 收集反馈与标注

* **[提交消息反馈](https://docs.dify.ai/zh/api-reference/feedback/submit-message-feedback.md)**：终端用户将回复评为 `like` 或 `dislike`，并可附加文字说明。
* **[获取应用的消息反馈](https://docs.dify.ai/zh/api-reference/feedback/list-app-feedbacks.md)**：返回应用内终端用户和管理员提交的全部反馈。

标注为问题预设固定答案，命中时应用直接返回该答案，不再生成新回复：

* **[创建标注](https://docs.dify.ai/zh/api-reference/annotations/create-annotation.md)**、**[获取标注列表](https://docs.dify.ai/zh/api-reference/annotations/list-annotations.md)**、**[更新标注](https://docs.dify.ai/zh/api-reference/annotations/update-annotation.md)**、**[删除标注](https://docs.dify.ai/zh/api-reference/annotations/delete-annotation.md)**：管理标注集合。
* **[配置标注回复](https://docs.dify.ai/zh/api-reference/annotations/configure-annotation-reply.md)**：开启或关闭标注匹配。该变更异步执行。
* **[查询标注回复配置任务状态](https://docs.dify.ai/zh/api-reference/annotations/get-annotation-reply-job-status.md)**：使用返回的任务 ID 轮询，确认变更已完成。


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
