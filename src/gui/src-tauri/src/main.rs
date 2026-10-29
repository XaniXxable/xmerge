#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Read;
use std::os::windows::process::CommandExt;
use std::process::Command;
use std::sync::Mutex;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(serde::Serialize)]
struct RunResult {
    code: i32,
    stdout: String,
    stderr: String,
}

#[tauri::command]
fn write_config(path: &str, content: &str) -> Result<(), String> {
    std::fs::write(path, content).map_err(|e| e.to_string())
}

#[tauri::command]
fn read_config(path: &str) -> Result<String, String> {
    std::fs::read_to_string(path).map_err(|e| e.to_string())
}

// PID of the currently running converter process; Windows taskkill terminates
// the whole tree, so no lock is held while the worker thread waits
static RUN_PID: Mutex<Option<u32>> = Mutex::new(None);

// settings live next to the GUI exe — deterministic across restarts
fn settings_file() -> std::path::PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.join("gui-settings.json")))
        .unwrap_or_else(|| std::path::PathBuf::from("gui-settings.json"))
}

#[tauri::command]
fn read_settings() -> Result<String, String> {
    std::fs::read_to_string(settings_file()).map_err(|e| e.to_string())
}

#[tauri::command]
fn write_settings(content: String) -> Result<(), String> {
    std::fs::write(settings_file(), content).map_err(|e| e.to_string())
}

/// Async command: the blocking wait runs on a worker thread, so the UI stays responsive.
#[tauri::command]
async fn run_exe(exe_path: String, args: Vec<String>) -> Result<RunResult, String> {
    tauri::async_runtime::spawn_blocking(move || run_exe_blocking(exe_path, args))
        .await
        .map_err(|e| format!("Task join failed: {e}"))?
}

fn run_exe_blocking(exe_path: String, mut args: Vec<String>) -> Result<RunResult, String> {
    // 1. resolve a relative exe path against the directory the Tauri GUI
    //    was started from — not against the converter's own location
    let exe = std::path::Path::new(&exe_path);
    let resolved_exe = if exe.is_absolute() {
        exe.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|e| format!("Cannot determine GUI working directory: {e}"))?
            .join(exe)
    };

    if !resolved_exe.exists() {
        return Err(format!("Converter not found: {}", resolved_exe.display()));
    }

    // 2. default working dir = where the Tauri GUI itself was started
    if !args.iter().any(|a| a == "-C") {
        let gui_dir = std::env::current_dir()
            .map_err(|e| format!("Cannot determine GUI working directory: {e}"))?;
        args.push("-C".into());
        args.push(gui_dir.to_string_lossy().into_owned());
    }

    // 3. spawn and remember the PID so `kill_run` can stop the process
    let mut child = Command::new(&resolved_exe)
        .args(&args)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|e| format!("Failed to start {}: {e}", resolved_exe.display()))?;

    *RUN_PID.lock().unwrap() = Some(child.id());

    // 4. drain stdout/stderr on reader threads while waiting — otherwise the
    //    pipes fill up (~64 KB), the converter blocks on its next write,
    //    and wait() never returns
    let stdout_pipe = child.stdout.take();
    let stderr_pipe = child.stderr.take();
    let t_out = std::thread::spawn(move || {
        let mut s = String::new();
        if let Some(mut o) = stdout_pipe { o.read_to_string(&mut s).ok(); }
        s
    });
    let t_err = std::thread::spawn(move || {
        let mut s = String::new();
        if let Some(mut o) = stderr_pipe { o.read_to_string(&mut s).ok(); }
        s
    });

    let status = child
        .wait()
        .map_err(|e| format!("Execution failed while waiting for the process: {e}"))?;
    let code = status.code().unwrap_or(-1);

    let stdout_buf = t_out.join().unwrap_or_default();
    let stderr_buf = t_err.join().unwrap_or_default();

    *RUN_PID.lock().unwrap() = None;

    Ok(RunResult {
        code,
        stdout: stdout_buf,
        stderr: stderr_buf,
    })
}

#[tauri::command]
fn kill_run() -> Result<(), String> {
    let pid = *RUN_PID.lock().unwrap();
    if let Some(pid) = pid {
        // /T kills the whole process tree, /F forces termination
        Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .map_err(|e| format!("Failed to stop the process: {e}"))?;
    }
    Ok(())
}

#[tauri::command]
fn open_path(path: String, app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    // normalize so Windows tools get backslash form even if the path
    // came from a mapping file with forward slashes
    let winpath = path.replace('/', "\\");
    let p = std::path::Path::new(&winpath);
    if !p.exists() {
        return Err(format!("File not found: {}", p.display()));
    }

    // does this extension have a registered application?
    // `assoc` is a cmd builtin: prints e.g. ".json=VSCode.json" or fails
    let has_assoc = match p.extension() {
        Some(e) => {
            let ext = format!(".{}", e.to_string_lossy().to_lowercase());
            Command::new("cmd")
                .args(["/C", "assoc", &ext])
                .creation_flags(CREATE_NO_WINDOW)
                .output()
                .map(|o| o.status.success() && !String::from_utf8_lossy(&o.stdout).trim().is_empty())
                .unwrap_or(false)
        }
        None => false,
    };

    if has_assoc {
        // registered -> open with the default application
        app.opener().open_path(winpath, None::<&str>).map_err(|e| e.to_string())
    } else {
        // no association registered -> go straight to the Windows
        // "Open with" picker; ShellExecute would show "Application not found"
        Command::new("rundll32")
            .args(["shell32.dll,OpenAs_RunDLL", &winpath])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Failed to open picker: {e}"))?;
        Ok(())
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            write_config,
            read_config,
            run_exe,
            kill_run,
            open_path,
            read_settings,
            write_settings
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}