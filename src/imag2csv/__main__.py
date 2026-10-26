"""`python -m imag2csv` で起動するためのエントリポイント。

uv が生成する `imag2csv.exe` ランチャーは未署名のため、Windows の
スマートアプリコントロール有効環境ではブロックされる。署名済みの
python.exe 経由で起動できるようにしておく。
"""
from .app import main

main()
