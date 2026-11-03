# Dify 服务的反向调用

# Dify 服务的反向调用

> 在插件中调用 Dify 平台的 App、Model、Tool 和 Node 服务

借助反向调用，插件可调用 Dify 主平台内的服务来扩展自身能力。

## 可调用的 Dify 模块

* **[App](https://docs.dify.ai/zh/develop-plugin/features-and-specs/advanced-development/reverse-invocation-app.md)**：访问 Dify 平台内 App 的数据。
* **[Model](https://docs.dify.ai/zh/develop-plugin/features-and-specs/advanced-development/reverse-invocation-model.md)**：调用 Dify 平台内的 LLM 能力，涵盖所有模型类型及 TTS、Rerank 等功能。
* **[Tool](https://docs.dify.ai/zh/develop-plugin/features-and-specs/advanced-development/reverse-invocation-tool.md)**：调用 Dify 平台内的其他工具类型插件。
* **[Node](https://docs.dify.ai/zh/develop-plugin/features-and-specs/advanced-development/reverse-invocation-node.md)**：调用 Dify 平台内特定 Chatflow/Workflow 应用中的节点。

## 相关资源

* [开发扩展插件](https://docs.dify.ai/zh/develop-plugin/dev-guides-and-walkthroughs/endpoint.md) - 了解如何开发与外部系统集成的插件
* [开发 Slack Bot 插件](https://docs.dify.ai/zh/develop-plugin/dev-guides-and-walkthroughs/develop-a-slack-bot-plugin.md) - 使用反向调用与 Slack 平台集成的示例
* [Bundle 类型插件](https://docs.dify.ai/zh/develop-plugin/features-and-specs/advanced-development/bundle.md) - 了解如何打包使用反向调用的多个插件
* [使用持久化存储](https://docs.dify.ai/zh/develop-plugin/features-and-specs/plugin-types/persistent-storage-kv.md) - 通过 KV 存储增强插件能力


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
