//! Loopback inference for the local assistant. Results are displayed as text.

use reqwest::{Client, Method, StatusCode, Url};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::Duration;

const DEFAULT_URL: &str = "http://127.0.0.1:1234/v1";
const MAX_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_INPUT_BYTES: usize = 12_000;
const PROBE_TIMEOUT: Duration = Duration::from_secs(5);
const INFERENCE_TIMEOUT: Duration = Duration::from_secs(120);

struct LocalModelClient {
    client: Client,
    base: Url,
    token: Option<String>,
}

impl LocalModelClient {
    fn from_env() -> Result<Self, String> {
        let base = std::env::var("LMSTUDIO_BASE_URL").unwrap_or_else(|_| DEFAULT_URL.into());
        let token = std::env::var("LMSTUDIO_API_KEY").ok();
        Self::new(&base, token)
    }

    fn new(base: &str, token: Option<String>) -> Result<Self, String> {
        let invalid = "LMSTUDIO_BASE_URL 必须是本机 HTTP 地址，例如 http://127.0.0.1:1234/v1";
        let mut base = Url::parse(base.trim()).map_err(|_| invalid.to_string())?;
        if base.scheme() != "http"
            || !matches!(base.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))
            || !base.username().is_empty()
            || base.password().is_some()
            || base.query().is_some()
            || base.fragment().is_some()
            || !matches!(base.path(), "/" | "/v1" | "/v1/")
        {
            return Err(invalid.into());
        }
        if base.host_str() == Some("localhost") {
            base.set_host(Some("127.0.0.1"))
                .map_err(|_| invalid.to_string())?;
        }
        base.set_path("/v1/");
        // The updater enables reqwest's rustls-no-provider feature globally.
        // Give this client its own provider without changing the updater's defaults.
        let tls = rustls::ClientConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .map_err(|_| "无法初始化 LM Studio HTTP 客户端".to_string())?
        .with_root_certificates(rustls::RootCertStore::empty())
        .with_no_client_auth();
        let client = Client::builder()
            .tls_backend_preconfigured(tls)
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(3))
            .build()
            .map_err(|_| "无法初始化 LM Studio HTTP 客户端".to_string())?;
        let token = token
            .map(|value| value.trim().to_owned())
            .filter(|value| !value.is_empty());
        Ok(Self {
            client,
            base,
            token,
        })
    }

    async fn request(
        &self,
        method: Method,
        path: &str,
        payload: Option<&Value>,
        timeout: Duration,
    ) -> Result<Value, String> {
        let url = self
            .base
            .join(path)
            .map_err(|_| "LM Studio 地址无效".to_string())?;
        let mut request = self.client.request(method, url).timeout(timeout);
        if let Some(token) = &self.token {
            request = request.bearer_auth(token);
        }
        if let Some(payload) = payload {
            request = request.json(payload);
        }
        let mut response = request.send().await.map_err(request_error)?;
        let status = response.status();
        if !status.is_success() {
            return Err(match status {
                StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                    "LM Studio 认证失败。请检查 LMSTUDIO_API_KEY 并重启 CAD Studio".into()
                }
                StatusCode::BAD_REQUEST | StatusCode::NOT_FOUND if path == "chat/completions" => {
                    format!("LM Studio 拒绝推理（HTTP {status}）。请确认模型已加载，并支持所选模式")
                }
                _ => format!("LM Studio 请求失败（HTTP {status}）。请检查本地服务及模型状态"),
            });
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(request_error)? {
            if chunk.len() > MAX_RESPONSE_BYTES - bytes.len() {
                return Err("LM Studio 响应超过大小限制".into());
            }
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| "LM Studio 返回了无效的 JSON 响应".into())
    }

    async fn models(&self) -> Result<Vec<String>, String> {
        let response = self
            .request(Method::GET, "/api/v1/models", None, PROBE_TIMEOUT)
            .await?;
        let list = serde_json::from_value::<ModelList>(response)
            .map_err(|_| "LM Studio 模型列表格式无效".to_string())?;
        Ok(list
            .models
            .into_iter()
            .filter(|model| model.kind == "llm")
            .flat_map(|model| model.loaded_instances)
            .map(|model| model.id)
            .filter(|id| !id.trim().is_empty())
            .collect())
    }

    async fn infer(&self, input: LocalModelRequest) -> Result<LocalModelReply, String> {
        let payload = inference_payload(&input)?;
        let models = self.models().await?;
        if models.is_empty() {
            return Err("LM Studio 当前没有可用模型，请先加载对话模型".into());
        }
        if !models.contains(&input.model) {
            return Err("所选模型当前不可用，请重新检查连接并选择模型".into());
        }
        let response = self
            .request(
                Method::POST,
                "chat/completions",
                Some(&payload),
                INFERENCE_TIMEOUT,
            )
            .await?;
        parse_reply(input.mode, &response)
    }
}

fn request_error(error: reqwest::Error) -> String {
    if error.is_timeout() {
        "LM Studio 请求超时。请确认模型就绪后重试".into()
    } else if error.is_connect() {
        "无法连接 LM Studio。请在 LM Studio 中启动本地 API 服务并检查端口".into()
    } else {
        "与 LM Studio 通信失败。请检查本地服务设置后重试".into()
    }
}

#[derive(Deserialize)]
struct ModelList {
    models: Vec<ModelInfo>,
}

#[derive(Deserialize)]
struct ModelInfo {
    #[serde(rename = "type")]
    kind: String,
    loaded_instances: Vec<ModelId>,
}

#[derive(Deserialize)]
struct ModelId {
    id: String,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
enum Mode {
    Chat,
    Plan,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum Role {
    User,
    Assistant,
}

#[derive(Deserialize, Serialize)]
struct Message {
    role: Role,
    content: String,
}

#[derive(Deserialize)]
pub(crate) struct LocalModelRequest {
    model: String,
    mode: Mode,
    messages: Vec<Message>,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub(crate) enum LocalModelReply {
    Chat { text: String },
    Plan { plan: Plan },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Plan {
    summary: String,
    assumptions: Vec<String>,
    steps: Vec<String>,
    checks: Vec<String>,
}

fn inference_payload(input: &LocalModelRequest) -> Result<Value, String> {
    if input.model.trim().is_empty() || input.model.len() > 512 {
        return Err("请选择 LM Studio 模型".into());
    }
    if !matches!(
        input.messages.last().map(|message| &message.role),
        Some(Role::User)
    ) || input.messages.len() > 9
        || input
            .messages
            .iter()
            .any(|message| message.content.trim().is_empty())
        || input
            .messages
            .iter()
            .map(|message| message.content.len())
            .sum::<usize>()
            > MAX_INPUT_BYTES
        || (matches!(input.mode, Mode::Plan) && input.messages.len() != 1)
    {
        return Err("请输入有效的问题或规划目标，长内容请分段发送".into());
    }
    let system = match input.mode {
        Mode::Chat => "你是 CAD Studio 本地问答助手。用用户的语言回答。只提供解释和建议，不声称运行过工具、验证过模型或修改过文件。不确定时指出缺少的信息。",
        Mode::Plan => "你是 CAD Studio 工程任务规划助手。除非用户指定其他语言，所有字段值都用简体中文。summary 描述拟完成的目标；assumptions 列出待确认的尺寸、材料等参数；steps 按先确认参数、再建模、后检查的顺序编写；checks 是可核对的验收条件。保留用户提供的尺寸和单位，不把未知值写成确定值，也不声称已执行或验证任务。",
    };
    let mut messages = vec![json!({"role": "system", "content": system})];
    messages.extend(input.messages.iter().map(|message| json!(message)));
    let mut payload = json!({
        "model": input.model, "messages": messages, "temperature": 0.2,
        "max_tokens": 1200, "stream": false
    });
    if matches!(input.mode, Mode::Plan) {
        payload["response_format"] = json!({
            "type": "json_schema", "json_schema": {
                "name": "cad_task_plan", "strict": true,
                "schema": {
                    "type": "object", "additionalProperties": false,
                    "properties": {
                        "summary": {"type": "string"},
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                        "steps": {"type": "array", "items": {"type": "string"}},
                        "checks": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["summary", "assumptions", "steps", "checks"]
                }
            }
        });
    }
    Ok(payload)
}

fn parse_reply(mode: Mode, response: &Value) -> Result<LocalModelReply, String> {
    let choice = &response["choices"][0];
    if choice["finish_reason"] == "length" {
        return Err("模型输出被截断。请缩短输入或拆分任务后重试".into());
    }
    let text = choice["message"]["content"]
        .as_str()
        .map(str::trim)
        .filter(|text| !text.is_empty() && choice["finish_reason"] == "stop")
        .ok_or_else(|| "LM Studio 未返回完整的文本回复".to_string())?;
    if matches!(mode, Mode::Chat) {
        return Ok(LocalModelReply::Chat { text: text.into() });
    }
    let invalid = "模型未返回有效的结构化计划。请缩小任务范围或更换支持结构化输出的模型";
    let plan: Plan = serde_json::from_str(text).map_err(|_| invalid.to_string())?;
    if plan.summary.trim().is_empty()
        || plan.steps.is_empty()
        || plan.checks.is_empty()
        || plan
            .assumptions
            .iter()
            .chain(&plan.steps)
            .chain(&plan.checks)
            .any(|item| item.trim().is_empty())
    {
        return Err(invalid.into());
    }
    Ok(LocalModelReply::Plan { plan })
}

#[tauri::command]
pub(crate) async fn lmstudio_models() -> Result<Vec<String>, String> {
    LocalModelClient::from_env()?.models().await
}

#[tauri::command]
pub(crate) async fn lmstudio_infer(request: LocalModelRequest) -> Result<LocalModelReply, String> {
    LocalModelClient::from_env()?.infer(request).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread;

    #[test]
    fn local_endpoint_keeps_requests_on_loopback() {
        let client = LocalModelClient::new("http://localhost:1234/v1", None).unwrap();
        assert_eq!(client.base.as_str(), "http://127.0.0.1:1234/v1/");
        for url in [
            "http://example.com/v1",
            "http://127.0.0.1.example.com/v1",
            "http://user@127.0.0.1/v1",
            "http://127.0.0.1/v1?token=x",
        ] {
            assert!(LocalModelClient::new(url, None).is_err(), "{url}");
        }
    }

    #[test]
    fn invalid_plan_and_truncated_reply_are_errors() {
        let response = json!({"choices": [{"finish_reason": "stop", "message": {"content":
            r#"{"summary":"test","assumptions":[],"steps":[],"checks":["review"]}"#
        }}]});
        assert!(parse_reply(Mode::Plan, &response).is_err());
        let truncated =
            json!({"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]});
        assert!(parse_reply(Mode::Chat, &truncated)
            .err()
            .unwrap()
            .contains("截断"));
    }

    #[test]
    fn http_failures_are_reported_without_response_body() {
        for (status, body, expected) in [
            ("401 Unauthorized", "private response", "认证失败"),
            ("200 OK", "<html>", "无效的 JSON"),
            (
                "302 Found\r\nLocation: http://127.0.0.1:1/v1/models",
                "",
                "HTTP 302",
            ),
        ] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let base = format!("http://{}", listener.local_addr().unwrap());
            let server = thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(3)))
                    .unwrap();
                let mut request = [0; 4096];
                let count = stream.read(&mut request).unwrap();
                assert!(request[..count].starts_with(b"GET /api/v1/models "));
                write!(
                    stream,
                    "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                )
                .unwrap();
            });
            let client = LocalModelClient::new(&base, None).unwrap();
            let error = tauri::async_runtime::block_on(client.models()).unwrap_err();
            assert!(error.contains(expected), "{error}");
            assert!(!error.contains("private response"));
            server.join().unwrap();
        }
    }

    #[test]
    #[ignore = "requires a local LM Studio server with a chat model"]
    fn lmstudio_live_model() {
        tauri::async_runtime::block_on(async {
            let models = lmstudio_models()
                .await
                .expect("discover live LM Studio model");
            let model = std::env::var("LMSTUDIO_TEST_MODEL").unwrap_or_else(|_| models[0].clone());
            assert!(models.contains(&model));
            let input = |mode, content: &str, model| LocalModelRequest {
                model,
                mode,
                messages: vec![Message {
                    role: Role::User,
                    content: content.into(),
                }],
            };
            let chat = lmstudio_infer(input(
                Mode::Chat,
                "一块长80 mm、宽40 mm的矩形板，俯视面积是多少平方毫米？只写计算式和结果。",
                model.clone(),
            ))
            .await
            .unwrap();
            let LocalModelReply::Chat { text } = chat else {
                panic!("expected chat reply")
            };
            assert!(
                text.replace([',', '，', ' '], "").contains("3200"),
                "{text}"
            );
            println!("model={model}; chat={text}");
            let plan = lmstudio_infer(input(Mode::Plan, "规划一块 80×40×6 mm 安装板和两个直径 5 mm 的通孔，孔距待确认。给出建模顺序和验收条件。", model)).await.unwrap();
            let LocalModelReply::Plan { plan } = plan else {
                panic!("expected plan")
            };
            assert!(plan.steps.len() >= 2);
            println!("plan={}", serde_json::to_string(&plan).unwrap());
            let missing = lmstudio_infer(input(
                Mode::Chat,
                "测试",
                "cad-studio-test-missing-model".into(),
            ))
            .await;
            assert!(missing.err().unwrap().contains("所选模型当前不可用"));
        });
    }
}
