# ADR 0001: 実行基盤の分担（WebView の TS、Rust、Python ワーカー）

- **Status**: Accepted
- **Date**: 2026-11-08
- **Decider**: メンテナー

## 決定

1. ドメインとユースケースは TypeScript の純関数として `packages/core` に置き、デスクトップアプリでは WebView の中で動かす。インストーラに Node や bun の実行環境は入れない
2. Rust（Tauri）は、OS との境界だけを受け持つ。ファイルの読み書き、ワーカーの起動と中継、OS の資格情報ストアにある API キー、LLM へのリクエストの送信が該当する
3. LLM のリクエストは TS が組み立て、Rust の `llm_send` が認証ヘッダを付けて送る。API キーを WebView に渡さない。送り先は登録済みの接続先に限る
4. 音声の推論（ボーカル分離、ASR、文字照合）は uv で管理する Python ワーカーが行う。stdio に 1 行 1 JSON で話し、形式は `protocol/worker.schema.json` を正本にする
5. 開発用の評価スクリプトは bun で `packages/core` を直接動かす。利用者向けの CLI は後のフェーズで作る

## 根拠

- 「キーを WebView に渡さない」「GUI と CLI で同じコードを通す」「インストーラを 50 MB 以下に保つ」を同時に満たす組み合わせが、ほかになかった
- 推論ライブラリ（faster-whisper、onnxruntime）は Python の配布物が最も成熟している（https://github.com/SYSTRAN/faster-whisper）
- LLM 各社の構造化出力は HTTP の JSON で完結し、SDK がなくても TS で組み立てられる

## 再評価トリガー

- Tauri が WebView 外での JS 実行を公式に提供したとき
- Python を使わずに分離と ASR を同等の精度で動かせるようになったとき（whisper.cpp と ONNX による置き換え）

## 不採用と理由

- Node のサイドカーで TS を動かす：インストーラが大きくなる
- ドメインを Rust で書く：UI と評価スクリプトで共有できない
- WebView から LLM へ直接送る：API キーが WebView に渡る
- Vercel AI SDK：キーを持つ側と組み立てる側が分けられない

## 代償

- LLM の接続先ごとの差は、TS の組み立てと Rust の送り先制限の 2 か所で扱う
- 利用者向け CLI は、提供するまで GUI と同じ経路を通らない

## 影響ファイル

- `packages/core/`、`protocol/worker.schema.json`、`workers/align/`
- 今後追加：`apps/desktop/src-tauri/src/llm/`、`packages/resolver/`
