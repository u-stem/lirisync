# Lirisync リポジトリの作業指示

歌の音声と歌詞の時刻を合わせ、AviUtl2 のプロジェクトとして書き出すデスクトップツール。構成と開発コマンドは `README.md`、実行基盤の分担は `docs/adr/0001-runtime-split.md`、現在有効な決定は `docs/adr/README.md` を読む。

## 言語

- コードとコメントは英語。README と `docs/` は日本語
- コミットメッセージは `<type>(<scope>): <日本語の説明>`。scope は `core` / `resolver` / `desktop` / `tauri` / `worker` / `protocol` / `aup2` / `exo` / `lrc` / `eval` / `docs` / `ci`

## 守ること

- 時刻は整数ミリ秒（`Ms`）で持つ。秒の浮動小数で計算しない。フレームへの変換は書き出し時に `msToFrame` だけで行う
- TypeScript は strict。`as` は型ガード関数の中だけ。外部からの値は Zod で parse してから使う
- ワーカーは標準出力に直接書かない。プロトコルの行は `ProtocolChannel` だけが書く。メッセージを変えるときは、先に `protocol/worker.schema.json` を変える
- 依存を足す前に、ライセンス・最終リリース日・代替候補を確かめ、`docs/dependencies.md` に記録する。許可するライセンスは `scripts/allowed-licenses.json`
- API キーを WebView・ログ・テストの録画に出さない
- 新機能はテストから書く。1 テスト 1 アサーション、Arrange-Act-Assert

## 確認コマンド

変更後は次を通す。

```sh
bun run lint && bun run typecheck && bun run test && bun run licenses
uv --directory workers/align run ruff check
uv --directory workers/align run ruff format --check
uv --directory workers/align run mypy
uv --directory workers/align run pytest
uv --directory workers/align run python tools/check_licenses.py
uv --directory eval/transcribe run ruff check
uv --directory eval/transcribe run ruff format --check
uv --directory eval/transcribe run mypy
uv --directory eval/transcribe run pytest
```

## 環境

- Mac ではドメイン・UI（ブラウザとモックのアダプター）・照合アルゴリズムを扱う。Tauri のビルド、GPU 推論、AviUtl2 での確認は Windows 機で行う
- Windows 専用のコードに macOS 用のスタブを書かない
