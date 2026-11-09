# 依存の一覧

採用した依存と、その根拠を記録する。配布版に入るのは「実行時」の依存だけで、CI のライセンス検査（`bun run licenses`、`workers/align/tools/check_licenses.py`）もこれだけを対象にする。

採用の基準は次の 5 つ。満たさないが検証に使いたいものは、評価用のコードに限って使う。

- ライセンス：MIT、Apache-2.0、BSD など、明示された寛容なライセンスであること。GPL、非商用、未記載は不可。例外として、GCC ランタイム例外（`GPL-3.0-or-later WITH GCC-exception-3.1`）付きのランタイムは許す。この例外は、ランタイムとリンクした側に GPL の条件を課さない
- 保守状況：直近 12 か月以内にリリースかコミットがあること
- 脆弱性：既知の未修正 CVE がないこと
- 再現性：ロックファイル（`bun.lock`、`uv.lock`）で版を固定すること
- 置き換え可能性：実行時の依存は、同じ役割の代替が 1 つ以上あること（言語本体と型定義は除く）

## TypeScript

| パッケージ | 版 | 区分 | ライセンス | 最終リリース | 用途 | 代替 |
| --- | --- | --- | --- | --- | --- | --- |
| zod | 4.6.7 | 実行時（core）、評価（eval） | MIT | 2026-10-12 | 外部入力の parse | valibot |
| typescript | 7.0.2 | 開発 | Apache-2.0 | 2026-07-08 | 型検査 | なし（言語本体） |
| @biomejs/biome | 2.6.6 | 開発 | MIT OR Apache-2.0 | 2026-11-06 | lint と整形 | ESLint と Prettier |
| @types/bun | 1.4.4 | 開発 | MIT | 2026-10-23 | `bun:test` などの型 | なし |

## Python（workers/align）

| パッケージ | 版 | 区分 | ライセンス | 最終リリース | 用途 | 代替 |
| --- | --- | --- | --- | --- | --- | --- |
| pydantic | 2.14.3 | 実行時 | MIT | 2026-11-05 | リクエストの検証 | msgspec |
| numpy | 2.5.4 | 実行時 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 2026-10-10 | 歌詞と ASR の文字列の全体照合（DP の行ごとのベクトル化） | 標準ライブラリだけの DP（1 曲で数十倍遅い） |
| sudachipy | 0.7.0 | 実行時 | Apache-2.0 | 2026-09-24 | 照合用テキストの読み仮名化 | fugashi（MeCab）と UniDic |
| sudachidict-core | 20261015 | 実行時 | Apache-2.0 | 2026-10-15 | SudachiPy の辞書 | sudachidict-small / sudachidict-full |
| pytest | 9.2.0 | 開発 | MIT | 2026-10-27 | テスト | unittest |
| ruff | 0.17.4 | 開発 | MIT | 2026-11-05 | lint と整形 | flake8 と black |
| mypy | 2.4.1 | 開発 | MIT | 2026-10-28 | 型検査 | pyright |
| jsonschema | 4.26.0 | 開発 | MIT | 2026-01-07 | 出力がスキーマに合うかのテスト | fastjsonschema |
| types-jsonschema | 4.26.0.20261006 | 開発 | Apache-2.0 | 2026-10-06 | jsonschema の型 | なし |
| packaging | 26.3 | 開発 | Apache-2.0 OR BSD-2-Clause | 2026-08-04 | ライセンス検査で依存の環境マーカーを評価する | なし（PyPA の標準実装） |

wheel に同梱されたネイティブのライブラリも、配布物に入る。パッケージの `License-Expression` はこれを含まないため、ライセンス検査はライセンスファイルの `Name:` と `License:` の欄も読む。`License:` を読めない項目は失敗にする。GCC ランタイム例外を許すのはこの同梱分だけで、パッケージ本体のライセンスには許さない。同梱の中身は OS ごとに違うので、この部分は配布先の Windows でだけ失敗にし、ほかの OS では警告にとどめる。numpy の Windows 版は OpenBLAS（BSD-3-Clause）、その中の LAPACK（BSD-3-Clause-Open-MPI）、GCC ランタイム（GCC ランタイム例外付き）を同梱する。macOS 版と Linux 版はさらに libquadmath（LGPL-2.1-or-later）を同梱するが、配布物には入らない。

pydantic が引き込む実行時の依存（pydantic-core、annotated-types、typing-extensions、typing-inspection）も、ライセンス検査の対象に入る。typing-extensions は PSF-2.0。

読み仮名化に pykakasi を使わないのは、GPL-3.0 で配布物に同梱できないためである。sudachidict-core は全体が Apache-2.0 だが、一部（`small_lex.csv` の一部と `matrix.def`）は UniDic 由来で BSD-3-Clause の著作権表示を伴う（SudachiDict の `LEGAL`）。配布版のライセンス表記には、この表示も載せる。

辞書を更新すると読みが変わり、コードを変えなくても照合の結果が変わりうる。版は `uv.lock` で固定し、上限は付けない（版が日付で、上限の値を決める根拠がないため）。sudachidict-core を更新するときは、同じ変更で Medium テスト（`tests/medium/test_sudachi_reader.py`）を通し、eval の結果を直近の値と比べる。

sudachipy は型スタブ（`sudachipy.pyi`）を同梱するが `py.typed` がないため、mypy の設定でこのスタブを読ませている。

確認日はすべて 2026-11-08。四半期ごとに保守状況を見直す。

## Python（eval/transcribe、評価専用）

評価用の書き起こしを作る `eval/transcribe`（faster-whisper で各曲の音声を書き起こす）の依存。配布版にもワーカーにも入らず、ライセンス検査の対象外である。上の採用基準のうち、ライセンスを満たさないものがあるが、評価用のコードに限って使う。

- faster-whisper は PyAV（`av`）を無条件に import する。PyAV の wheel は FFmpeg を同梱する。macOS 版の wheel の同梱物（`.dylibs`）には、LGPL の部分に加えて `libx264` と `libx265`（GPL）が入っているのを確かめた。Windows 版の中身は確かめていないが、配布物には入れられない
- GPU で動かすときは、ctranslate2 が NVIDIA の CUDA ライブラリを要求する。これは NVIDIA の独自ライセンスで、再配布できない

| パッケージ | 版 | 区分 | ライセンス | 最終リリース | 用途 | 代替 |
| --- | --- | --- | --- | --- | --- | --- |
| faster-whisper | 1.2.1 | 評価 | MIT | 2025-10-31 | 書き起こし（単語の時刻つき） | whisper.cpp、openai-whisper |
| ctranslate2 | 4.8.5 | 評価 | MIT | 2026-11-02 | faster-whisper の推論エンジン | なし（faster-whisper の必須依存） |
| av | 18.1.0 | 評価 | BSD-3-Clause（同梱の FFmpeg は LGPL と GPL） | 2026-08-12 | 音声ファイルのデコード | なし（faster-whisper の必須依存）。事前に WAV へ変換すれば不要だが import は残る |
| onnxruntime | 1.31.1 | 評価 | MIT | 2026-10-26 | 音声区間検出（`--vad`）の Silero VAD | なし（faster-whisper の必須依存） |
| huggingface-hub | 2.4.0 | 評価 | Apache-2.0 | 2026-10-29 | モデルの取得 | 手作業でのダウンロード |
| tokenizers | 0.23.3 | 評価 | Apache-2.0 | 2026-10-09 | Whisper のトークナイザ | なし（faster-whisper の必須依存） |
| tqdm | 4.70.1 | 評価 | MPL-2.0 AND MIT | 2026-09-11 | 進捗の表示 | rich |
| pytest | 9.2.0 | 開発 | MIT | 2026-10-27 | テスト | unittest |
| ruff | 0.17.4 | 開発 | MIT | 2026-11-05 | lint と整形 | flake8 と black |
| mypy | 2.4.1 | 開発 | MIT | 2026-10-28 | 型検査 | pyright |

faster-whisper が引き込む実行時の依存（`uv.lock` のとおり）も、評価用の環境に入る。numpy 2.5.4、protobuf 7.36.2、flatbuffers 25.12.19、hf-xet 1.8.0、httpx2 2.16.0、httpcore2 2.16.0、h11 0.16.0、anyio 4.16.0、idna 3.20、httpx2-jsfetch 1.0（emscripten のみ）、truststore 0.10.5、pyyaml 6.0.3、click 8.5.1、colorama 0.4.6（Windows のみ）、fsspec 2026.9.0、filelock 4.2.9、packaging 26.3、typing-extensions 4.16.0。ライセンスは PyPI の記載で MIT、BSD-3-Clause、Apache-2.0、PSF-2.0 のいずれか（numpy は上の表と同じ複合）。

tokenizers の PyPI のメタデータには `License` の欄がなく、分類子（classifier）だけが Apache Software License を示す。リポジトリ（huggingface/tokenizers）の `LICENSE` ファイルも Apache-2.0 なので、表にはこれを書いた。

faster-whisper の最終リリースは 2025-10-31 で 12 か月を超えたが、リポジトリには 2026-11-06 にもコミットがある。評価専用なので、このまま使う。

faster-whisper 1.2.1 は `av.open(metadata_errors=...)` を呼ぶが、PyAV 19 でこの引数がなくなった（18.1.0 は受け付け、19.0.0 は `TypeError`）。faster-whisper の要求は `av>=11` だけなので、`eval/transcribe/pyproject.toml` で `av>=16,<19` に絞っている。faster-whisper を更新するときは、この上限を外せるか確かめる。

確認日は 2026-11-10。
