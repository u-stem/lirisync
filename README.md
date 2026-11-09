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

# 評価用の書き起こしツール（配布しない）
uv --directory eval/transcribe sync
uv --directory eval/transcribe run ruff check
uv --directory eval/transcribe run ruff format --check
uv --directory eval/transcribe run mypy
uv --directory eval/transcribe run pytest
```

配布版に入れる依存は、MIT・Apache-2.0・BSD などの寛容なライセンスに限ります。許可するライセンスは `scripts/allowed-licenses.json` にあり、CI で検査します。

## ライセンス

[MIT](LICENSE)
