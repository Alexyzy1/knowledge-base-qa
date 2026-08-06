# Qwen3-ASR API 接口文档

>  **Base URL**: `http://<host>:<port>`
>  **兼容协议**: 本接口兼容 [OpenAI Audio Speech API](https://platform.openai.com/docs/api-reference/audio/createSpeech)，可直接替换 OpenAI SDK 的 `base_url` 使用。

------

## 目录

1. [认证](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#认证)
2. [请求参数](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#请求参数)
3. [音频格式支持](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#音频格式支持)
4. [非流式模式](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#非流式模式non-stream)
5. [流式模式（SSE）](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#流式模式sse)
6. [响应结构](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#响应结构)
7. [错误码](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#错误码)
8. [性能指标](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#性能指标)
9. [OpenAI SDK 接入说明](https://claude.ai/chat/d78daf6e-4d59-4d5f-81a9-cd9d0f66b818#openai-sdk-接入说明)

------

## 认证

所有请求需在 Header 中携带 Bearer Token：

```
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

------

## 请求参数

| 参数                      | 类型    | 是否必填 | 说明                                                  |
| ------------------------- | ------- | -------- | ----------------------------------------------------- |
| `model`                   | string  | **必填** | 模型名称，如 `Qwen3-ASR-1.7B`                         |
| `messages`                | array   | **必填** | 消息数组，包含 user 角色的多模态内容                  |
| `messages[].role`         | string  | **必填** | 固定为 `"user"`                                       |
| `messages[].content`      | array   | **必填** | 内容块数组，必须包含 `audio_url` 类型块               |
| `content[].type`          | string  | **必填** | `"audio_url"` 表示音频块，`"text"` 表示文本提示       |
| `content[].audio_url.url` | string  | **必填** | 音频来源，支持 base64 data URL                        |
| `stream`                  | boolean | 可选     | `false`（默认）返回完整响应；`true` 开启 SSE 流式推送 |
| `temperature`             | number  | 可选     | 建议设为 `0.01` 以获得确定性转写结果，范围 0–2        |

**`content[].audio_url.url` 格式：**

```
# base64 data URL
data:audio/wav;base64,<base64编码内容>
```

------

## 音频格式支持

| 格式 | MIME 类型    |
| ---- | ------------ |
| WAV  | `audio/wav`  |
| MP3  | `audio/mpeg` |
| FLAC | `audio/flac` |
| OGG  | `audio/ogg`  |
| M4A  | `audio/mp4`  |

------

## 非流式模式（Non-Stream）

`stream: false`，服务端处理完成后一次性返回完整 JSON。

### Python 示例

```python
import base64
import httpx

# 读取本地音频并编码为 base64
with open("audio.wav", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()
audio_url = f"data:audio/wav;base64,{b64}"

payload = {
    "model": "Qwen3-ASR-1.7B",
    "stream": False,
    "temperature": 0.01,
    "messages": [{
        "role": "user",
        "content": [
            {
                "type": "audio_url",
                "audio_url": {"url": audio_url}
            },
            # 可选：上下文提示词
            {"type": "text", "text": "会议纪要"}
        ]
    }]
}

resp = httpx.post(
    "http://<BASE_URL>/v1/chat/completions",
    json=payload,
    headers={
        "Authorization": "Bearer <API_KEY>",
        "Content-Type": "application/json"
    },
    timeout=120.0
)

text = resp.json()["choices"][0]["message"]["content"]
print(text)
# 输出会带有一个前缀'language Chinese<asr_text>'
```

### cURL 示例

```bash
B64=$(base64 -w0 audio.wav)

curl -X POST http://<BASE_URL>/v1/chat/completions \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3-ASR-1.7B",
    "stream": false,
    "temperature": 0.01,
    "messages": [{
      "role": "user",
      "content": [{
        "type": "audio_url",
        "audio_url": {
          "url": "data:audio/wav;base64,'"$B64"'"
        }
      }]
    }]
  }'
```

------

## 流式模式（SSE）

`stream: true`，服务端以 Server-Sent Events 格式逐步推送转写内容，最终以 `data: [DONE]` 结束。

### Python 示例

```python
import base64
import json
import httpx

with open("audio.wav", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()
audio_url = f"data:audio/wav;base64,{b64}"

payload = {
    "model": "Qwen3-ASR-1.7B",
    "stream": True,
    "temperature": 0.01,
    "messages": [{
        "role": "user",
        "content": [{
            "type": "audio_url",
            "audio_url": {"url": audio_url}
        }]
    }]
}

with httpx.Client(timeout=120.0) as client:
    with client.stream(
        "POST",
        "http://<BASE_URL>/v1/chat/completions",
        json=payload,
        headers={
            "Authorization": "Bearer <API_KEY>",
            "Content-Type": "application/json"
        }
    ) as resp:
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            delta = (json.loads(raw)["choices"][0]
                     ["delta"].get("content", ""))
            print(delta, end="", flush=True)
```

### cURL 示例

```bash
B64=$(base64 -w0 audio.wav)

curl -X POST http://<BASE_URL>/v1/chat/completions \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "model": "Qwen3-ASR-1.7B",
    "stream": true,
    "temperature": 0.01,
    "messages": [{
      "role": "user",
      "content": [{
        "type": "audio_url",
        "audio_url": {
          "url": "data:audio/wav;base64,'"$B64"'"
        }
      }]
    }]
  }'
```

------

## 响应结构

### 非流式响应（HTTP 200 · application/json）

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "model": "Qwen3-ASR-1.7B",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "language Chinese<asr_text>人工智能正在改变我们的生活方式"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 128,
    "completion_tokens": 14,
    "total_tokens": 142
  }
}
```

**转写文本路径**：`choices[0].message.content`

------

### 流式响应（HTTP 200 · text/event-stream）

每行格式为 `data: <JSON>`，以 `data: [DONE]` 结束。

```
# 首个 chunk（含角色信息）
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"}}]}

# 内容 chunk（一个或多个）
data: {"choices":[{"delta":{"content":"language Chinese<asr_text>人工智能"}}]}
data: {"choices":[{"delta":{"content":"正在改变我们的生活"}}]}

# 结束 chunk（含停止原因）
data: {"choices":[{"delta":{},"finish_reason":"stop"}]}

# 流终止标志
data: [DONE]
```

**增量文本路径**：`choices[0].delta.content`

------

## 错误码

| HTTP 状态码 | 含义                  | 常见原因                                     |
| ----------- | --------------------- | -------------------------------------------- |
| `401`       | Unauthorized          | API Key 无效或缺失                           |
| `400`       | Bad Request           | 请求体格式错误、音频格式不支持               |
| `422`       | Unprocessable Entity  | 缺少必填字段（model / messages / audio_url） |
| `500`       | Internal Server Error | 模型推理失败                                 |
| `503`       | Service Unavailable   | 服务器过载或模型未加载                       |

------

## 性能指标

| 指标                            | 说明                                |
| ------------------------------- | ----------------------------------- |
| **RTF**（Real Time Factor）     | `总耗时 / 音频时长`，值越小性能越好 |
| **TTFC**（Time To First Chunk） | 流式模式下首个内容 chunk 的到达延迟 |
| 建议超时时间                    | `120s`                              |
| 建议 temperature                | `0.01`（确定性转写）                |

> **注意**：base64 编码会使 payload 体积增大约 33%。对于时长超过 60 秒的音频，建议优先使用远程 HTTP URL，以避免请求体过大。

------

## OpenAI SDK 接入说明

该接口与 OpenAI Chat Completions API 完全兼容，只需替换 `base_url` 即可接入任何 OpenAI 兼容客户端。

### Python OpenAI SDK

```python
from openai import OpenAI
import base64

client = OpenAI(
    base_url="http://<BASE_URL>/v1",
    api_key="<API_KEY>"
)

with open("audio.wav", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

response = client.chat.completions.create(
    model="Qwen3-ASR-1.7B",
    temperature=0.01,
    messages=[{
        "role": "user",
        "content": [{
            "type": "audio_url",
            "audio_url": {"url": f"data:audio/wav;base64,{b64}"}
        }]
    }]
)

print(response.choices[0].message.content)
```

### 流式接入（OpenAI SDK）

```python
stream = client.chat.completions.create(
    model="Qwen3-ASR-1.7B",
    temperature=0.01,
    stream=True,
    messages=[{
        "role": "user",
        "content": [{
            "type": "audio_url",
            "audio_url": {"url": f"data:audio/wav;base64,{b64}"}
        }]
    }]
)

for chunk in stream:
    delta = chunk.choices[0].delta.content or ""
    print(delta, end="", flush=True)
```

> **说明**：`audio_url` 内容块类型是 vLLM 多模态扩展，与 OpenAI 原生的 `/v1/audio/transcriptions` 接口不同。确保客户端支持多模态内容块的传递即可正常使用。