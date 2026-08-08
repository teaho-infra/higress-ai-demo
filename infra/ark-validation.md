# Task 2b 验证记录: 豆包 Ark 端点

## 验证命令
```bash
curl -X GET "https://ark.cn-beijing.volces.com/api/coding/v3/models" \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

## 结果
- HTTP 200 ✅
- 返回 JSON: 包含多个 LLM 模型

## 可用 LLM 模型(2026-07 列表,支持 function_calling)
- `glm-5-2-260617` — 智谱 GLM 5.2,1M context
- `deepseek-v4-flash-ga-260731` — DeepSeek V4 Flash,1M context
- `doubao-seed-*` — 豆包 seed 系列(待确认具体子型号)

## 备注
- ⚠️ 实际对话子型号(Task 7 时确认 `OPENAI_MODEL` 默认值)
- Higress 不再强制作为 LLM 网关(它的 Provider 注册是 K8s 资源,headless 难搞);
  Spring AI Demo 直接 `base-url` 指向豆包 Ark 端点。Higress 留给 MCP 路由用。

## 关键决定
**Spring AI Demo 的 `spring.ai.openai.base-url` 直接指 `https://ark.cn-beijing.volces.com/api/coding/v3`,不绕道 Higress。**
(原 plan 想"经 Higress 代理",改成"直连 Ark",省事)
