# 決定索引

現在有効な決定を 1 行ずつ並べる。1 行に収まらない判断だけを ADR にする。ADR は採番後に編集せず、覆すときは新しい ADR を起こしてこの表を書き換える。

| 決定 | 根拠 | 再評価トリガー | 退けた案 | 出典 |
| --- | --- | --- | --- | --- |
| ドメインは WebView の TS、OS 境界は Rust、推論は Python ワーカー | キーの秘匿、GUI と CLI の共有、インストーラの小ささを同時に満たす | Tauri の JS 実行環境、Python 不要の推論 | Node サイドカー、Rust ドメイン | [ADR 0001](0001-runtime-split.md) |
| 時刻は整数ミリ秒で持ち、フレームへの変換は書き出し時に整数演算で行う | 浮動小数の秒では 4.1 秒 × 30 fps が 122.999… になり 1 フレームずれる | なし | 浮動小数の秒 | `packages/core/src/domain/time.ts` |
| ワーカーは元の標準出力をプロトコル専用に複製し、fd 1 を stderr に向ける。プロトコルの行には `@@lirisync ` を付ける | 推論ライブラリが標準出力に進捗やログを書く | Windows 実機で接頭辞のない行がプロトコルに混ざったとき | 標準出力をそのまま使う | `workers/align/src/lirisync_worker/protocol.py` |
| 配布版には寛容なライセンス（MIT、Apache-2.0、BSD、OFL など）の依存だけを入れる | 無償の OSS として配布する | なし | GPL や非商用の依存を同梱する | [dependencies.md](../dependencies.md) |
