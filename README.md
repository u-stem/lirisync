# Lirisync（りりしんく）

歌の音声と歌詞から、各行の表示タイミングを自動で合わせるデスクトップツールです。結果は AviUtl2 のプロジェクト（`.aup2`）として書き出し、そのまま歌詞動画の編集に使えます。

> 開発を始めたばかりで、まだアプリとしては動きません。いまは土台となるコードと、精度を確かめる準備を進めています。

## できるようになること

- ボーカルを分離し、音声認識の結果と歌詞を照合して、行ごとの開始・終了時刻を求めます
- 繰り返しのサビなどで照合が曖昧な区間は、LLM で補正します（任意。API キーは OS の資格情報ストアに保存します）
- 波形を見ながら、タイミングを手で直せます
- AviUtl2 の `.aup2`、旧 AviUtl の `.exo`、単語単位の Enhanced LRC を書き出します

対象は Windows です。GPU（NVIDIA）がなくても動きますが、解析に時間がかかります。

## 構成

| ディレクトリ | 内容 |
| --- | --- |
| `packages/core` | ドメインとユースケース（TypeScript の純関数）。時刻は整数ミリ秒で持ちます |
| `workers/align` | 推論を受け持つ Python ワーカー。stdio で 1 行 1 JSON を話します |
| `protocol/worker.schema.json` | ワーカーとのメッセージ形式の正本 |
| `eval/` | 整列の精度を測る評価セットと指標。使い方は [eval/README.md](eval/README.md) |
| `scripts/` | 開発用のスクリプト（依存のライセンス検査など） |
| `docs/` | 決定記録（`docs/adr/`）と依存の一覧 |

デスクトップアプリ（Tauri と Next.js）は、これから `apps/desktop` に追加します。実行基盤の分担は [ADR 0001](docs/adr/0001-runtime-split.md) にまとめています。

## 開発

必要なもの：[bun](https://bun.sh/) 1.4 以降、[uv](https://docs.astral.sh/uv/) 0.13 以降。

### Windows 機をまとめて整える

Windows 機では、スクリプト 1 本で、ツールの導入から依存の取得、モデルの取得までを済ませられます。管理者権限は要りません。スクリプトは git を入れないので、先に git を入れ、クローンしたフォルダで実行します。

1. git が入っていなければ、PowerShell で `winget install --id Git.Git -e` を実行して入れます。
2. PowerShell を開き直し、`git clone https://github.com/u-stem/lirisync.git` でクローンして、そのフォルダに移ります。
3. クローンしたフォルダで、スクリプトを実行します。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
```

実行ポリシーはこの実行にだけ回避し、恒久的には変えません。何度実行してもかまいません。更新したいときは `git pull` をして、スクリプトをもう一度実行してください。入っているツールは飛ばし、取得済みで SHA-256 の合うモデルも取り直しません。

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `-ModelsDir` | `C:\lirisync-models` | モデルの置き場所。分離モデルは `<ModelsDir>\separator`、文字 CTC モデルは `<ModelsDir>\aligner`、CUDA のライブラリは `<ModelsDir>\cuda` に置きます |
| `-SkipTools` | なし | winget を使いません。ツールは先に `PATH` に入れておいてください |
| `-SkipModels` | なし | モデルも CUDA のライブラリも取得しません |
| `-SkipCuda` | なし | CUDA のライブラリ（約 1.4 GB）を取得しません。書き起こしは CPU で走ります |

スクリプトは、`PATH` に無いものだけを winget で入れます（git は手順 1 で入れるので対象外です）。

| コマンド | winget の ID |
| --- | --- |
| `uv` | `astral-sh.uv` |
| `bun` | `Oven-sh.Bun` |
| `ffmpeg` | `Gyan.FFmpeg` |

そのあと `bun install --frozen-lockfile` と、2 か所の `uv sync --locked` を動かし、2 つのモデルを取得します。NVIDIA の GPU があれば、書き起こしを GPU で動かすための CUDA のライブラリも取得します。入れた直後のツールを同じ実行で使えるよう、`PATH` はレジストリから読み直します。それでも見つからないときは、PowerShell を開き直して再実行してください。

ffmpeg（Gyan のビルド）は開発用で、配布物には入りません。

CUDA のライブラリ（cuBLAS、cuDNN、NVRTC）は、`eval/transcribe/cuda-requirements.txt` で版とハッシュを固定した NVIDIA の wheel を、`uv pip install --target` で `<ModelsDir>\cuda` に入れます。NVIDIA のライセンスなので、`uv.lock` にもリポジトリにも入れません。評価専用で、配布物にも入りません。NVIDIA のドライバは入れないので、先に入れておいてください。NVIDIA の GPU が見つからないときは、この手順を飛ばします。

### 手で行う場合

```sh
# TypeScript
bun install
bun run lint
bun run typecheck
bun run test
bun run licenses   # 実行時の依存のライセンスを検査する

# Python ワーカー
uv --directory workers/align sync
uv --directory workers/align run ruff check
uv --directory workers/align run mypy
uv --directory workers/align run pytest
uv --directory workers/align run python tools/check_licenses.py

# ボーカル分離モデルの参照テスト（任意。モデルはリポジトリに含めない）
uv --directory workers/align run python tools/fetch_separator_model.py --dest ~/lirisync-separator
LIRISYNC_SEPARATOR_DIR=~/lirisync-separator uv --directory workers/align run pytest tests/medium/test_separator_reference.py

# 文字 CTC モデル（照合の 2 段目）の確認テスト（任意。モデルはリポジトリに含めない）
uv --directory workers/align run python tools/fetch_aligner_model.py --dest ~/lirisync-aligner
LIRISYNC_ALIGNER_DIR=~/lirisync-aligner uv --directory workers/align run pytest tests/medium/test_aligner_real_model.py

# 評価用の書き起こしツール（配布しない）
uv --directory eval/transcribe sync
uv --directory eval/transcribe run ruff check
uv --directory eval/transcribe run ruff format --check
uv --directory eval/transcribe run mypy
uv --directory eval/transcribe run pytest
```

ボーカル分離の参照テストは手動で動かします。モデル（約 240 MB の int8 版）と参照出力はリポジトリに含めないため、環境変数 `LIRISYNC_SEPARATOR_DIR` が未設定かファイルが足りないと skip され、CI では動きません。`workers/align/src/lirisync_worker/separation/` を変えたら、上の 2 行（取得とテスト）で動かしてください。Windows でも動かし、SNR を PR に記録します（ファイルには残しません）。取得するファイルは固定した版と SHA-256 で検査します。`--fp16` を付けると GPU 用の fp16 版（約 460 MB）と参照出力も取得しますが、取得するだけで、fp16 を使う参照テストはまだありません。

int8 のモデルは、モデルカードによると AVX512-VNNI と AVX-VNNI を持つ CPU で正確で、VNNI のない古い x86 では飽和することがあります（上流では測っていません）。このテストの 47.5 dB は Apple silicon で測った値です。しきい値の 40 dB は目標ではなく下限で、移植が正しい場合と、レイアウトや STFT の誤り（ほぼ 0 dB になる）を分けるために置いています。

文字 CTC モデルの確認テストも手動で動かします。モデル（約 360 MB の int8 版）と語彙はリポジトリに含めないため、環境変数 `LIRISYNC_ALIGNER_DIR` が未設定かファイルが足りないと skip され、CI では動きません。`workers/align/src/lirisync_worker/ctc_model.py` と `ctc_tokens.py` を変えたら、上の 2 行（取得とテスト）で動かしてください。取得するファイルは固定した版と SHA-256 で検査します。

ワーカーの `separate` は、音声のデコードと WAV の書き出しに ffmpeg を別プロセスで呼びます。開発中は `PATH` の `ffmpeg` を使い、別の実行ファイルを使うときは環境変数 `LIRISYNC_FFMPEG` にそのパスを入れます。見つからないと `ffmpeg_missing` を返します。実モデルを通すテスト（`tests/medium/test_separate_real_model.py`）は、`LIRISYNC_SEPARATOR_DIR` が未設定か ffmpeg がないと skip されます。

ワーカーの `refine`（照合の 2 段目）は、1 段目で決まった窓ごとに歌詞を文字 CTC モデルで強制整列し、行の開始・終了を整数ミリ秒で返します。音声は ffmpeg で 16 kHz モノラルにデコードします。窓の前後に足す余裕（`marginMs`）は呼び出し側が決め、ワーカーに既定値はありません。余裕を足して音声の長さで切った窓が 30 秒を超える行は、強制せずに `too_long` として返します。実モデルを通すテスト（`tests/medium/test_refine_real_model.py`）は、`LIRISYNC_ALIGNER_DIR` が未設定か ffmpeg がないと skip されます。

配布版に入れる依存は、MIT・Apache-2.0・BSD などの寛容なライセンスに限ります。許可するライセンスは `scripts/allowed-licenses.json` にあり、CI で検査します。

## ライセンス

[MIT](LICENSE)
