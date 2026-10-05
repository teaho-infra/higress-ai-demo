package main

import (
    "strings"

    "github.com/higress-group/proxy-wasm-go-sdk/proxywasm"
    "github.com/higress-group/proxy-wasm-go-sdk/proxywasm/types"
    "github.com/higress-group/wasm-go/pkg/log"
    "github.com/higress-group/wasm-go/pkg/wrapper"
    "github.com/tidwall/gjson"
)

type Config struct {
    allowedHost string
    message     string
    blocked     bool
}

func main() {}

func init() {
    wrapper.SetCtx(
        "leon-hello",
        wrapper.ParseConfigBy(parseConfig),
        wrapper.ProcessRequestHeadersBy(onRequestHeaders),
    )
}

func parseConfig(value gjson.Result, config *Config, logger log.Log) error {
    config.allowedHost = value.Get("allowed_host").String()
    if config.allowedHost == "" {
        config.allowedHost = "wasm-demo.local"
    }
    config.message = value.Get("message").String()
    if config.message == "" {
        config.message = "Hello from leon-hello!"
    }
    config.blocked = value.Get("blocked").Bool()
    return nil
}

func onRequestHeaders(ctx wrapper.HttpContext, config Config, logger log.Log) types.Action {
    ctx.DontReadRequestBody()

    host, err := proxywasm.GetHttpRequestHeader(":authority")
    if err != nil {
        return types.ActionContinue
    }
    // 本示例使用 DNS 域名；去掉客户端可能附带的端口。
    host = strings.SplitN(host, ":", 2)[0]
    if !strings.EqualFold(host, config.allowedHost) {
        return types.ActionContinue
    }

    path, err := proxywasm.GetHttpRequestHeader(":path")
    if err != nil || strings.SplitN(path, "?", 2)[0] != "/hello" {
        return types.ActionContinue
    }

    code := uint32(200)
    detail := "leon-hello.reply"
    body := config.message + "\n"
    if config.blocked {
        code = 403
        detail = "leon-hello.blocked"
        body = "Blocked by leon-hello\n"
    }

    headers := [][2]string{
        {"content-type", "text/plain; charset=utf-8"},
        {"x-leon-wasm", "0.1.0"},
    }
    if err := proxywasm.SendHttpResponseWithDetail(code, detail, headers, []byte(body), -1); err != nil {
        logger.Errorf("local response failed: %v", err)
    }
    return types.ActionContinue
}
