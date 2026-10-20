"""Convert verified official ASL weights to GGUF and prepare an official Windows CPU runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings

BUILD = "b11497"
WEIGHTS = {
    "model.safetensors-00001-of-00002.safetensors": "d62b120d137aefcc1729b8bcd568536eee966473df2a0b318e9332aac97ddd61",
    "model.safetensors-00002-of-00002.safetensors": "8ea2abca4a2195737ca1547e6cbbcdf9290d173cc530f0c561d008e94512de3d",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent":"ASL-local-setup"})
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    temporary.replace(destination)


def extract(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        root = destination.resolve()
        for member in bundle.infolist():
            if not (root / member.filename).resolve().is_relative_to(root):
                raise RuntimeError("Archive contains a path outside the target directory")
        bundle.extractall(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default=settings.llm_model_path)
    parser.add_argument("--tools-dir", default=str(ROOT / ".llm-runtime" / "llama.cpp"))
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    model = Path(args.model_dir).resolve()
    tools = Path(args.tools_dir).resolve()
    tools.mkdir(parents=True, exist_ok=True)
    for name, expected in WEIGHTS.items():
        file = model / name
        if not file.is_file() or digest(file) != expected:
            raise RuntimeError(f"Missing or invalid official weights: {file}. Complete setup_llm.py --download-only first.")
    executable = tools / "runtime" / "llama-server.exe"
    if not executable.is_file():
        request = urllib.request.Request(f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{BUILD}", headers={"User-Agent":"ASL-local-setup"})
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
        asset = next(a for a in release["assets"] if a["name"] == f"llama-{BUILD}-bin-win-cpu-x64.zip")
        archive = tools / "runtime.zip"
        download(asset["browser_download_url"], archive)
        if asset.get("digest") and asset["digest"] != "sha256:" + digest(archive):
            raise RuntimeError("Official runtime archive SHA256 mismatch")
        extract(archive, tools / "runtime")
    converter = tools / f"llama.cpp-{BUILD}" / "convert_hf_to_gguf.py"
    if not converter.is_file():
        archive = tools / "source.zip"
        download(f"https://github.com/ggml-org/llama.cpp/archive/refs/tags/{BUILD}.zip", archive)
        extract(archive, tools)
    converted = model / "ASL-4B-v1-BF16.gguf"
    output = model / "ASL-4B-v1-Q4_K_M.gguf"
    provenance = output.with_suffix(".provenance.json")
    verified_output = False
    if output.is_file() and provenance.is_file():
        record = json.loads(provenance.read_text(encoding="utf-8"))
        verified_output = record.get("revision") == settings.llm_revision and record.get("gguf_sha256") == digest(output)
    if not verified_output:
        subprocess.run([sys.executable, "-B", str(converter), str(model), "--outfile", str(converted),
            "--outtype", "bf16", "--no-nextn", "--model-name", settings.llm_model], check=True)
        temporary = output.with_suffix(".gguf.part")
        subprocess.run([str(tools / "runtime" / "llama-quantize.exe"), str(converted), str(temporary), "Q4_K_M", str(settings.llm_cpu_threads)], check=True)
        temporary.replace(output)
        record = {"model":settings.llm_model, "revision":settings.llm_revision, "source_sha256":WEIGHTS,
            "runtime_build":BUILD, "quantization":"Q4_K_M", "gguf_sha256":digest(output)}
        provenance.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"CPU ASL prepared: {output}", flush=True)
    print(f"Set LLM_ENGINE=llama_cpp, LLM_SERVER_EXECUTABLE={executable}, LLM_GGUF_PATH={output}", flush=True)
    if args.verify or args.serve:
        settings.llm_engine = "llama_cpp"
        settings.llm_server_executable = str(executable)
        settings.llm_gguf_path = str(output)
        sys.argv = ["setup_llm.py", "--verify-only", "--model-dir", str(model)] + (["--serve"] if args.serve else [])
        from setup_llm import main as verify
        return verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
