use std::{path::Path, time::Duration};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub async fn snapshot(root: &Path, recovery: bool) -> Result<super::LocalSnapshot, String> {
    let value = request(
        root,
        serde_json::json!({"version":1,"method":"snapshot","recovery":recovery}),
        5,
    )
    .await?;
    serde_json::from_value(value).map_err(|_| "client_snapshot_unavailable".into())
}

pub async fn request(
    root: &Path,
    request: serde_json::Value,
    seconds: u64,
) -> Result<serde_json::Value, String> {
    tokio::time::timeout(Duration::from_secs(seconds), async {
        #[cfg(unix)]
        let mut stream = tokio::net::UnixStream::connect(root.join("desktop-ipc/desktop.sock"))
            .await
            .map_err(|_| "client_ipc_unavailable")?;
        #[cfg(windows)]
        let mut stream = {
            let name = std::fs::read_to_string(root.join("desktop-pipe"))
                .map_err(|_| "client_ipc_unavailable")?;
            if !name.starts_with(r"\\.\pipe\agent-manager-desktop-") || name.len() > 160 {
                return Err("client_ipc_invalid_endpoint".to_string());
            }
            tokio::net::windows::named_pipe::ClientOptions::new()
                .open(name)
                .map_err(|_| "client_ipc_unavailable")?
        };
        let request = format!("{request}\n");
        stream
            .write_all(request.as_bytes())
            .await
            .map_err(|_| "client_ipc_transport_failed")?;
        let mut body = Vec::new();
        stream
            .take(16 * 1024 * 1024 + 1)
            .read_to_end(&mut body)
            .await
            .map_err(|_| "client_ipc_transport_failed")?;
        if body.len() > 16 * 1024 * 1024 {
            return Err("client_snapshot_too_large".to_string());
        }
        let value: serde_json::Value =
            serde_json::from_slice(&body).map_err(|_| "client_snapshot_unavailable".to_string())?;
        if let Some(error) = value.get("error").and_then(|v| v.as_str()) {
            return Err(error.to_owned());
        }
        Ok(value)
    })
    .await
    .map_err(|_| "client_ipc_timeout".to_string())?
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixListener;

    #[test]
    fn snapshot_protocol_and_invalid_response() {
        let root =
            std::path::PathBuf::from("/tmp").join(format!("desktop-ipc-{}", std::process::id()));
        std::fs::create_dir_all(root.join("desktop-ipc")).unwrap();
        let listener = UnixListener::bind(root.join("desktop-ipc/desktop.sock")).unwrap();
        let worker = std::thread::spawn(move || {
            for response in [
                r#"{"local":{},"inventory":{"client_id":"fixture"},"revision":"7","pending":[],"scan_history":[],"quarantine":[]}"#,
                r#"{"error":"client_snapshot_unavailable"}"#,
            ] {
                let (mut stream, _) = listener.accept().unwrap();
                let mut request = String::new();
                BufReader::new(&mut stream).read_line(&mut request).unwrap();
                let request: serde_json::Value = serde_json::from_str(&request).unwrap();
                assert_eq!(request["version"], 1);
                assert_eq!(request["method"], "snapshot");
                assert_eq!(request["recovery"], true);
                stream.write_all(response.as_bytes()).unwrap();
            }
        });
        let runtime = tokio::runtime::Runtime::new().unwrap();
        let result = runtime.block_on(snapshot(&root, true)).unwrap();
        assert_eq!(result.revision, "7");
        assert_eq!(result.inventory["client_id"], "fixture");
        assert!(result.pending.unwrap().as_array().unwrap().is_empty());
        assert!(matches!(
            runtime.block_on(snapshot(&root, true)),
            Err(error) if error == "client_snapshot_unavailable"
        ));
        worker.join().unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }
}
