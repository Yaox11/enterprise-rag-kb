# 安装 difyctl

# 安装 difyctl

> 用一行脚本或手动下载二进制文件安装 difyctl

`difyctl` 是一个独立的二进制文件，无任何运行时依赖。安装脚本会检测你的平台，从 Dify 的 GitHub Releases 下载匹配的构建版本，校验其校验和，并完成安装。

> [!NOTE]
>
> `difyctl` 随 Dify 1.15.0 首次发布。每个构建版本对应特定的 Dify 版本，请安装与你的服务器相匹配的版本（见下文的 `DIFY_VERSION`）。

## 安装

**1. 运行安装程序**

**macOS / Linux**

支持的平台：macOS 和 Linux，x64 和 arm64。

```bash theme={null}
curl -fsSL https://raw.githubusercontent.com/langgenius/dify/main/cli/scripts/install-cli.sh | DIFY_VERSION=1.17.1 sh
```

脚本会安装到 `~/.local/bin/difyctl`，并在该目录不在你的 `PATH` 中时提示你。

**Windows**

支持的平台：x64。

```powershell theme={null}
$env:DIFY_VERSION = "1.17.1"
irm https://raw.githubusercontent.com/langgenius/dify/main/cli/scripts/install.ps1 | iex
```

脚本会安装到 `%LOCALAPPDATA%\difyctl\bin\difyctl.exe`，如果该目录尚未加入 `PATH`，会打印将其加入 `PATH` 的命令。

**手动下载**

1. 从 [Dify 的 GitHub Releases](https://github.com/langgenius/dify/releases) 中，选择与服务器 Dify 版本匹配的发布版本，并下载两个资源文件：

   * 适用于你平台的二进制文件（`difyctl-v<version>-<os>-<arch>`）
   * 校验和清单（`difyctl-v<version>-checksums.txt`）

2. 计算二进制文件的 SHA-256 哈希值，并与 checksums 文件中对应的条目比对。

   如果两者不一致，说明下载文件已损坏或被篡改；删除它并重新下载。

   ```bash macOS / Linux theme={null}
   shasum -a 256 difyctl-v<version>-<os>-<arch>
   ```

   ```powershell Windows theme={null}
   Get-FileHash difyctl-v<version>-windows-x64.exe
   ```

3. 将二进制文件加入 `PATH`：

   ```bash macOS / Linux theme={null}
   chmod +x difyctl-v<version>-<os>-<arch>
   mv difyctl-v<version>-<os>-<arch> ~/.local/bin/difyctl
   ```

   ```powershell Windows theme={null}
   New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\difyctl\bin" | Out-Null
   Move-Item difyctl-v<version>-windows-x64.exe "$env:LOCALAPPDATA\difyctl\bin\difyctl.exe"
   ```

> [!TIP]
>
> 如需自定义安装，可在运行安装命令时设置以下环境变量。
>
> | 变量 | 说明 | 示例 |
> | - | - | - |
> | `DIFY_VERSION` | 用于安装 `difyctl` 的 Dify 发布标签，取自 [Dify Releases](https://github.com/langgenius/dify/releases)。 默认使用最新发布版本；当服务器不是最新版本时，将其设置为服务器的发布标签。 | `1.16.1` |
> | `DIFYCTL_VERSION` | 固定使用特定的 `difyctl` 构建版本。仅在未设置 `DIFY_VERSION` 时生效。 | `0.2.0-alpha` |
> | `DIFYCTL_PREFIX` | 安装目录（默认 `~/.local`）。二进制文件会放在 `<prefix>/bin` 下。 | `/usr/local` |
>
> 例如：
>
> ```bash macOS / Linux theme={null}
> curl -fsSL https://raw.githubusercontent.com/langgenius/dify/main/cli/scripts/install-cli.sh | DIFY_VERSION=1.16.1 sh
> ```
>
> ```powershell Windows theme={null}
> # PowerShell 没有内联写法，该设置在当前会话剩余时间内生效
> $env:DIFY_VERSION = "1.16.1"
> irm https://raw.githubusercontent.com/langgenius/dify/main/cli/scripts/install.ps1 | iex
> ```

**2. 验证安装**

```bash theme={null}
difyctl version
```

你应当看到一个 `Client:` 区块，其中包含版本和平台信息。

如果你看到的是 `command not found`，说明安装目录不在你的 `PATH` 中。将它加入：

```bash macOS / Linux theme={null}
# add to ~/.zshrc or ~/.bashrc; running it inline only lasts until the session ends
export PATH="$HOME/.local/bin:$PATH"
```

```powershell Windows theme={null}
[Environment]::SetEnvironmentVariable('PATH', "$env:LOCALAPPDATA\difyctl\bin;$env:PATH", 'User')
```

## 更新

要更新 `difyctl`，重新运行上面的安装命令，新版本会直接覆盖原有的二进制文件。

## 卸载

```bash macOS / Linux theme={null}
rm ~/.local/bin/difyctl
```

```powershell Windows theme={null}
Remove-Item -Recurse "$env:LOCALAPPDATA\difyctl"
```

要在卸载前退出登录，运行 [`difyctl auth logout`](https://docs.dify.ai/zh/cloud/cli/reference/auth-and-contexts#退出登录)。

## 后续步骤

装好 `difyctl` 后，前往 [快速开始](https://docs.dify.ai/zh/cloud/cli/quick-start.md) 登录并运行你的第一个应用。


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
