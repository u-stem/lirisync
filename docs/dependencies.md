# 依存の一覧

採用した依存と、その根拠を記録する。配布版に入るのは「実行時」の依存だけで、CI のライセンス検査（`bun run licenses`、`workers/align/tools/check_licenses.py`）もこれだけを対象にする。

採用の基準は次の 5 つ。満たさないが検証に使いたいものは、評価用のコードに限って使う。

- ライセンス：MIT、Apache-2.0、BSD など、明示された寛容なライセンスであること。GPL、非商用、未記載は不可
- 保守状況：直近 12 か月以内にリリースかコミットがあること
- 脆弱性：既知の未修正 CVE がないこと
- 再現性：ロックファイル（`bun.lock`、`uv.lock`）で版を固定すること
- 置き換え可能性：実行時の依存は、同じ役割の代替が 1 つ以上あること（言語本体と型定義は除く）

## TypeScript

| パッケージ | 版 | 区分 | ライセンス | 最終リリース | 用途 | 代替 |
| --- | --- | --- | --- | --- | --- | --- |
| zod | 4.6.7 | 実行時（core） | MIT | 2026-10-12 | 外部入力の parse | valibot |
| typescript | 7.0.2 | 開発 | Apache-2.0 | 2026-07-08 | 型検査 | なし（言語本体） |
| @biomejs/biome | 2.6.6 | 開発 | MIT OR Apache-2.0 | 2026-11-06 | lint と整形 | ESLint と Prettier |
| @types/bun | 1.4.4 | 開発 | MIT | 2026-10-23 | `bun:test` などの型 | なし |

## Python（workers/align）

| パッケージ | 版 | 区分 | ライセンス | 最終リリース | 用途 | 代替 |
| --- | --- | --- | --- | --- | --- | --- |
| pydantic | 2.14.3 | 実行時 | MIT | 2026-11-05 | リクエストの検証 | msgspec |
| sudachipy | 0.7.0 | 実行時 | Apache-2.0 | 2026-09-24 | 照合用テキストの読み仮名化 | fugashi（MeCab）と UniDic |
| rapidfuzz | 3.14.6 | 実行時 | MIT | 2026-08-30 | 歌詞行と ASR セグメントの文字類似度 | 標準ライブラリの difflib |
| sudachidict-core | 20261015 | 実行時 | Apache-2.0 | 2026-10-15 | SudachiPy の辞書 | sudachidict-small / sudachidict-full |
| pytest | 9.2.0 | 開発 | MIT | 2026-10-27 | テスト | unittest |
| ruff | 0.17.4 | 開発 | MIT | 2026-11-05 | lint と整形 | flake8 と black |
| mypy | 2.4.1 | 開発 | MIT | 2026-10-28 | 型検査 | pyright |
| jsonschema | 4.26.0 | 開発 | MIT | 2026-01-07 | 出力がスキーマに合うかのテスト | fastjsonschema |
| types-jsonschema | 4.26.0.20261006 | 開発 | Apache-2.0 | 2026-10-06 | jsonschema の型 | なし |
| packaging | 26.3 | 開発 | Apache-2.0 OR BSD-2-Clause | 2026-08-04 | ライセンス検査で依存の環境マーカーを評価する | なし（PyPA の標準実装） |

pydantic が引き込む実行時の依存（pydantic-core、annotated-types、typing-extensions、typing-inspection）も、ライセンス検査の対象に入る。typing-extensions は PSF-2.0。

読み仮名化に pykakasi を使わないのは、GPL-3.0 で配布物に同梱できないためである。sudachidict-core は全体が Apache-2.0 だが、一部（`small_lex.csv` の一部と `matrix.def`）は UniDic 由来で BSD-3-Clause の著作権表示を伴う（SudachiDict の `LEGAL`）。配布版のライセンス表記には、この表示も載せる。

辞書を更新すると読みが変わり、コードを変えなくても照合の結果が変わりうる。版は `uv.lock` で固定し、上限は付けない（版が日付で、上限の値を決める根拠がないため）。sudachidict-core を更新するときは、同じ変更で Medium テスト（`tests/medium/test_sudachi_reader.py`）を通し、eval の結果を直近の値と比べる。

照合の手順は lyric-align の公開された実測を参考に、自前で実装した（コードは移していない）。類似度は lyric-align の difflib に替えて RapidFuzz の Indel 類似度を使う。どちらも `2 × 共通部分の長さ ÷ 両方の長さの和` で、lyric-align が difflib で測ったしきい値をそのまま初期値に使える。

sudachipy は型スタブ（`sudachipy.pyi`）を同梱するが `py.typed` がないため、mypy の設定でこのスタブを読ませている。

確認日はすべて 2026-11-08。四半期ごとに保守状況を見直す。
