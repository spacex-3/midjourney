# wechat-gptbot momoyu插件

本项目作为 `wechat-gptbot` 插件，可以调用 mj api 接口。


## 安装指南

### 1. 添加插件源
在 `plugins/source.json` 文件中添加以下配置：
```
{
  "momoyu": {
    "repo": "https://github.com/spacex-3/midjourney.git",
    "desc": "midjourney代理画图"
  }
}
```

### 2. 插件配置
在 `config.json` 文件中添加以下配置：
```
plugins: 

  - name: midjourney
    command: [画]
    openai_api_base: https://api.***.ai/v1
    openai_api_key: sk-***
    proxy_server: https://api.***.ai/mj
    api_key: sk-***

```