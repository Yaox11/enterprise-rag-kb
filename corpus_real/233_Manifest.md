# Manifest

# Manifest

> 插件 manifest 的 YAML schema，用于声明名称、作者、运行时、资源、权限，以及插件附带的工具、模型和端点

manifest 是一个定义插件基本信息的 YAML 文件，包括名称、作者、包含的工具和模型等。如果文件格式不正确，插件的解析和打包会失败。

关于插件的整体架构，详见 [插件开发基本概念](https://docs.dify.ai/zh/develop-plugin/getting-started/getting-started-dify-plugin.md) 和 [开发者速查表](https://docs.dify.ai/zh/develop-plugin/dev-guides-and-walkthroughs/cheatsheet.md)。

## 代码示例

下面是一个简单的 manifest 文件，每个字段都会在后续的「结构」一节中说明。实际示例可参考 [Google 工具插件 manifest](https://github.com/langgenius/dify-official-plugins/blob/main/tools/google/manifest.yaml)。

```yaml theme={null}
version: 0.0.1
type: "plugin"
author: "Yeuoly"
name: "neko"
label:
  en_US: "Neko"
created_at: "2024-07-12T08:03:44.658609186Z"
icon: "icon.svg"
resource:
  memory: 1048576
  permission:
    tool:
      enabled: true
    model:
      enabled: true
      llm: true
    endpoint:
      enabled: true
    app:
      enabled: true
    storage:
      enabled: true
      size: 1048576
plugins:
  endpoints:
    - "provider/neko.yaml"
meta:
  version: 0.0.1
  arch:
    - "amd64"
    - "arm64"
  runner:
    language: "python"
    version: "3.12"
    entrypoint: "main"
privacy: "./privacy.md"
```

## 结构

**version** `version` *required*

插件版本。

**type** `string` *required*

插件类型。目前仅支持 `plugin`，未来将支持 `bundle`。

**author** `string` *required*

作者，定义为市场中的组织名称。

**label** `object` *required*

多语言名称。

**created\_at** `RFC3339` *required*

创建时间。市场要求该时间不能晚于当前时间。

**icon** `string` *required*

图标路径。

**resource** `object`

插件申请的资源。

**memory** `int64`

最大内存使用量，单位为字节。主要与 Dify Cloud 上的 AWS Lambda 资源分配相关。

**permission** `object`

插件申请的权限。

**tool** `object`

反向调用工具的权限。

**enabled** `boolean`

是否启用工具权限。

**model** `object`

反向调用模型的权限。

**enabled** `boolean`

是否启用模型权限。

**llm** `boolean`

是否启用大语言模型权限。

**text\_embedding** `boolean`

是否启用文本嵌入模型权限。

**rerank** `boolean`

是否启用重排序模型权限。

**tts** `boolean`

是否启用文本转语音模型权限。

**speech2text** `boolean`

是否启用语音转文本模型权限。

**moderation** `boolean`

是否启用内容审核模型权限。

**node** `object`

反向调用节点的权限。

**enabled** `boolean`

是否启用节点权限。

**endpoint** `object`

注册 `endpoint` 的权限。

**enabled** `boolean`

是否启用 endpoint 权限。

**app** `object`

反向调用 `app` 的权限。

**enabled** `boolean`

是否启用 app 权限。

**storage** `object`

申请持久化存储的权限。

**enabled** `boolean`

是否启用存储权限。

**size** `int64`

允许的最大持久化存储大小，单位为字节。

**plugins** `object` *required*

列出插件所扩展能力对应的 YAML 文件，使用插件包内的绝对路径。例如，要扩展一个模型，需定义一个类似 `openai.yaml` 的文件并在此列出其路径。该路径下必须存在对应文件，否则打包会失败。

> [!WARNING]
>
> 以下组合不被允许：
>
> * 同时扩展工具和模型。
> * 同时扩展模型和 Endpoints。
> * 没有任何扩展。
>
> 目前，每种扩展类型仅支持一个 provider。

**tools** `array[string]`

[工具](https://docs.dify.ai/zh/develop-plugin/dev-guides-and-walkthroughs/tool-plugin.md) provider 的插件扩展。

**models** `array[string]`

[模型](https://docs.dify.ai/zh/develop-plugin/features-and-specs/plugin-types/model-designing-rules.md) provider 的插件扩展。

**endpoints** `array[string]`

[Endpoints](https://docs.dify.ai/zh/develop-plugin/dev-guides-and-walkthroughs/develop-a-slack-bot-plugin.md) provider 的插件扩展。

**agent\_strategies** `array[string]`

[Agent 策略](https://docs.dify.ai/zh/develop-plugin/features-and-specs/advanced-development/reverse-invocation.md) provider 的插件扩展。

**meta** `object` *required*

插件的元数据。

**version** `version` *required*

manifest 格式版本。初始版本为 `0.0.1`。

**arch** `array[string]` *required*

支持的架构。目前仅支持 `amd64` 和 `arm64`。

**runner** `object` *required*

运行时配置。

**language** `string` *required*

编程语言。目前仅支持 Python。

**version** `string` *required*

语言版本。目前仅支持 `3.12`。

**entrypoint** `string` *required*

程序入口点。Python 下应为 `main`。

**privacy** `string`

插件隐私政策的相对路径或 URL，例如 `"./privacy.md"` 或 `"https://your-web/privacy"`。**在 Dify 市场上架时必填**，插件须明确说明如何使用用户数据。详见 [插件隐私数据保护指南](https://docs.dify.ai/zh/develop-plugin/publishing/standards/privacy-protection-guidelines.md)。


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
