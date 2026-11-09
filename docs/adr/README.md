# 決定索引

現在有効な決定を 1 行ずつ並べる。1 行に収まらない判断だけを ADR にする。ADR は採番後に編集せず、覆すときは新しい ADR を起こしてこの表を書き換える。

| 決定 | 根拠 | 再評価トリガー | 退けた案 | 出典 |
| --- | --- | --- | --- | --- |
| ドメインは WebView の TS、OS 境界は Rust、推論は Python ワーカー | キーの秘匿、GUI と CLI の共有、インストーラの小ささを同時に満たす | Tauri の JS 実行環境、Python 不要の推論 | Node サイドカー、Rust ドメイン | [ADR 0001](0001-runtime-split.md) |
| 時刻は整数ミリ秒で持ち、フレームへの変換は書き出し時に整数演算で行う | 浮動小数の秒では 4.1 秒 × 30 fps が 122.999… になり 1 フレームずれる | なし | 浮動小数の秒 | `packages/core/src/domain/time.ts` |
| ワーカーは元の標準出力をプロトコル専用に複製し、fd 1 を stderr に向ける。プロトコルの行には `@@lirisync ` を付ける | 推論ライブラリが標準出力に進捗やログを書く | Windows 実機で接頭辞のない行がプロトコルに混ざったとき | 標準出力をそのまま使う | `workers/align/src/lirisync_worker/protocol.py` |
| ワーカーのメッセージは `protocol/worker.schema.json` を正本とし、TS（Zod）と Python（pydantic）の型は手で書く。一致はテストで確かめる。TS はスキーマから作った判定と合格・不合格の例で比べ、Python は実際の出力をスキーマで検証する | スキーマが小さく、生成器を足すほどではない。生成した型は `Ms` のブランドを持てない | 手書きの型とスキーマのずれが、テストをすり抜けたとき | 型の自動生成 | `eval/test/adapters/worker-protocol.test.ts` |
| 配布版には寛容なライセンス（MIT、Apache-2.0、BSD、OFL など）の依存だけを入れる。wheel に同梱されたライブラリも対象で、GCC ランタイム例外付きのランタイムは許す | 無償の OSS として配布する。ランタイム例外は、リンクした側に GPL の条件を課さない | なし | GPL や非商用の依存を同梱する | [dependencies.md](../dependencies.md) |
| 照合は 2 段。1 段目は ASR と歌詞の読みの文字単位の全体照合で位置と一致率を出し、2 段目は行の周辺だけで強制整列して時刻を詰める | ASR との一致率は歌詞と独立した証拠で失敗が見える。強制整列の誤りは 1 段目の窓に閉じ込める | 検証フェーズで 2 段目が誤差の裾を縮めないとき | 前方の貪欲な行照合、強制整列だけ、Whisper への歌詞の強制 | [ADR 0002](0002-two-stage-alignment.md) |
| 評価用の書き起こしは eval 専用の uv プロジェクト（`eval/transcribe`）で faster-whisper を使い、ワーカーと配布版には入れない | faster-whisper は PyAV（FFmpeg を同梱し、macOS 版の wheel には GPL の x264 と x265 も入っている）を必須とし、GPU 用の CUDA ライブラリは NVIDIA の独自ライセンスで、配布版のライセンス方針に合わない。評価用のコードなら使える | 配布版の ASR エンジンを決めたとき | ワーカーに faster-whisper を入れる | `eval/transcribe/pyproject.toml` |
