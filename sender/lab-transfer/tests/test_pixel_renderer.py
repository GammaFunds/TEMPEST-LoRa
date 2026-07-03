from __future__ import annotations

import base64
import gc
import hashlib
import json
import struct
import unittest
import zlib
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tempest_lora_lab import (
    CAPTURE_GOLDEN_SYMBOL_FIXTURE_SHA256,
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    CaptureReplayRendererProfile,
    DynamicPhyParameters,
    DynamicPixelRendererProfile,
    ProfileId,
    ProtocolError,
    SymbolEnvelope,
    normalize_capture_symbols,
    normalize_dynamic_symbols,
    render_dynamic_envelope,
    replay_capture_fixture,
)
from tempest_lora_lab import pixel_renderer
from tempest_lora_lab.protocol import canonical_json_bytes


R2D2H_BUNDLE_BASE64 = (
    "eyJjaGlycF92ZWN0b3JzIjp7ImRvd25fazAiOnsiYmxhY2tfcGl4ZWxzIjoxODk5OSwiZmlyc3Rf"
    "d2hpdGUiOjEsImxhc3Rfd2hpdGUiOjM4MDEyLCJzaGEyNTYiOiJhZGZkODQxODJkYmYwZTQ2OWIw"
    "NTI2YWFhZjUyOWQxYmYzYTRmNzJmODEzZjdkYWUxZjM5NWEzZDc0MTY1MDI3Iiwid2hpdGVfcGl4"
    "ZWxzIjoxOTAxN30sImRvd25fazEiOnsiYmxhY2tfcGl4ZWxzIjoxODk5NiwiZmlyc3Rfd2hpdGUi"
    "OjEsImxhc3Rfd2hpdGUiOjM4MDEyLCJzaGEyNTYiOiIxYzdiMmIyNWRkNWRjNjAwYjA4YjU0ZjRk"
    "MDRkMTI3ODQ1OWMzOGNjYmQyNDBjNmNlOTlkZjZiMTQ1ODczNWRmIiwid2hpdGVfcGl4ZWxzIjox"
    "OTAyMH0sImRvd25fazEyNyI6eyJibGFja19waXhlbHMiOjE5MDI0LCJmaXJzdF93aGl0ZSI6MSwi"
    "bGFzdF93aGl0ZSI6MzgwMTIsInNoYTI1NiI6ImE1MjVhYTg4ZjBjZGZmYTIzYmNkMTM1OTQwZTVk"
    "YzQ3ZDc2YWJiMDBjZjkzNDAxNzY0NThkMzU0ZGJjYWFhN2IiLCJ3aGl0ZV9waXhlbHMiOjE4OTky"
    "fSwiZG93bl9rMTMiOnsiYmxhY2tfcGl4ZWxzIjoxOTAxMSwiZmlyc3Rfd2hpdGUiOjEsImxhc3Rf"
    "d2hpdGUiOjM4MDEyLCJzaGEyNTYiOiJhYjZkMmM0ZTExYjg4MjUwMTUyMGIxZTU4YzJiMTYxNjdi"
    "NTk3MjU1N2E3YmYyNjUyZmMyMmY5NGU5YmMzYmQzIiwid2hpdGVfcGl4ZWxzIjoxOTAwNX0sImRv"
    "d25fazE2Ijp7ImJsYWNrX3BpeGVscyI6MTkwNDMsImZpcnN0X3doaXRlIjoxLCJsYXN0X3doaXRl"
    "IjozODAxMiwic2hhMjU2IjoiMTI3ZTM3ZWQyYzJkZjZmY2MyNmE0NWNjMGI2MzkzMmU0NjY1YWYz"
    "YzdhZWMzMGM2M2JjNmRlMDg3ODE5ZjgxZCIsIndoaXRlX3BpeGVscyI6MTg5NzN9LCJkb3duX2s2"
    "NCI6eyJibGFja19waXhlbHMiOjE4OTc0LCJmaXJzdF93aGl0ZSI6MSwibGFzdF93aGl0ZSI6Mzgw"
    "MTIsInNoYTI1NiI6IjYzYWI5OGU3ZjIzZjZiYmViNDY4NjY1ZjY4OWIyNWY0YTViYmZmZWIyMGFm"
    "MjBlMDVjYmNlNmJhN2I3MWExYzkiLCJ3aGl0ZV9waXhlbHMiOjE5MDQyfSwiZG93bl9rOCI6eyJi"
    "bGFja19waXhlbHMiOjE4OTk5LCJmaXJzdF93aGl0ZSI6MSwibGFzdF93aGl0ZSI6MzgwMTIsInNo"
    "YTI1NiI6ImQ1NGU5OTEzZmYyMTNhYTNhMTA0MzZmMGY0ZGI1NmU4NGMyMWE0OTEzMDRkYjYzYmY4"
    "ZjkzMmUxOGVmOTMxNTgiLCJ3aGl0ZV9waXhlbHMiOjE5MDE3fSwidXBfazAiOnsiYmxhY2tfcGl4"
    "ZWxzIjoxOTA1MSwiZmlyc3Rfd2hpdGUiOjEsImxhc3Rfd2hpdGUiOjM4MDEyLCJzaGEyNTYiOiIx"
    "OTk4NWVjZmFiMmFlMTM1NTMzMzY5MTZhMjlmNWM1YmQzYzgxZGZjMzExYmNjYmE3OWNjYTI0MWZk"
    "YTA2MDlhIiwid2hpdGVfcGl4ZWxzIjoxODk2NX0sInVwX2sxIjp7ImJsYWNrX3BpeGVscyI6MTkw"
    "MjUsImZpcnN0X3doaXRlIjoxLCJsYXN0X3doaXRlIjozODAxMiwic2hhMjU2IjoiZTUzM2UyMTQ4"
    "NWJhYjUxNTI2NGJlMjNlYTRiM2U3NjM2MWM3OTdhM2JhMDM4NzJkOTlmMDBhZmE5MDkzZmUzMCIs"
    "IndoaXRlX3BpeGVscyI6MTg5OTF9LCJ1cF9rMTI3Ijp7ImJsYWNrX3BpeGVscyI6MTg5OTUsImZp"
    "cnN0X3doaXRlIjoxLCJsYXN0X3doaXRlIjozODAxMiwic2hhMjU2IjoiZGU2NTUzYmMzZjhlNDI3"
    "YzU1NGE0YmZkZmJlNjdiM2JjMjEzZGU1ZGZlZWRlM2ExYzcxYTkxZmU0NDY1MGM1OSIsIndoaXRl"
    "X3BpeGVscyI6MTkwMjF9LCJ1cF9rMTMiOnsiYmxhY2tfcGl4ZWxzIjoxOTAyOCwiZmlyc3Rfd2hp"
    "dGUiOjEsImxhc3Rfd2hpdGUiOjM4MDEyLCJzaGEyNTYiOiI4OWNjOGZlMDk1NmE1Y2U1NjIwNGMy"
    "ZDkyZTk5YzU4Mjc5YWVkZmFlYzY2MTA4MTc5NzljYjJkNDUyMGRjMWZlIiwid2hpdGVfcGl4ZWxz"
    "IjoxODk4OH0sInVwX2sxNiI6eyJibGFja19waXhlbHMiOjE4OTkxLCJmaXJzdF93aGl0ZSI6MSwi"
    "bGFzdF93aGl0ZSI6MzgwMTIsInNoYTI1NiI6Ijc1MzBlMjhjMDMyYjI1ZDRhYzRiODdmODJlMWNh"
    "YTNiMGMyNTc3NTA5ZmFlNmViZjc5ZWUwMzIyNDIwMmM2NzciLCJ3aGl0ZV9waXhlbHMiOjE5MDI1"
    "fSwidXBfazY0Ijp7ImJsYWNrX3BpeGVscyI6MTkwNDIsImZpcnN0X3doaXRlIjoxLCJsYXN0X3do"
    "aXRlIjozODAxMiwic2hhMjU2IjoiOGU4NjQ0MjdmZmMyMmRkNjQxZjBiZWQ1NGYwNjVmOTgxYTRk"
    "OTk5ODMzODc2YjU0YTY1ODliMmUzNjEyOWJhYyIsIndoaXRlX3BpeGVscyI6MTg5NzR9LCJ1cF9r"
    "OCI6eyJibGFja19waXhlbHMiOjE5MDI1LCJmaXJzdF93aGl0ZSI6MSwibGFzdF93aGl0ZSI6Mzgw"
    "MTIsInNoYTI1NiI6IjdkNGUzMWIwMDczYmZmYjAzMWRhOWNlOTEwODVjMTEzNDU4YWQ0ZTZmMDE5"
    "ZWI4ZGIyNmE4MzkxMGVjNDVkNDUiLCJ3aGl0ZV9waXhlbHMiOjE4OTkxfX0sImZvcm11bGEiOnsi"
    "Y2hpcF9jb3VudCI6MTI4LCJjaGlycF9waXhlbHMiOjM4MDE2LCJkb3duX2ZyZXF1ZW5jeV9vcmRl"
    "ciI6WyJjZW50ZXIrYmFuZHdpZHRoLzIiLCJjZW50ZXItYmFuZHdpZHRoLzIiXSwiZnJlcXVlbmN5"
    "X21vZHVsdXNfaHoiOjE0ODUwMDAwMCwicGhhc2VfZGVub21pbmF0b3IiOjU2NDUzNzYwMDAwMDAs"
    "InNhbXBsZV9pbmRleCI6InQ9MC4uTi0xIiwic2hpZnRlZF9wb3NpdGlvbiI6IihzaGlmdCt0KSVO"
    "Iiwic3ltYm9sX3NoaWZ0IjoiTipLLy8xMjgiLCJ1cF9mcmVxdWVuY3lfb3JkZXIiOlsiY2VudGVy"
    "LWJhbmR3aWR0aC8yIiwiY2VudGVyK2JhbmR3aWR0aC8yIl0sIndoaXRlX3ByZWRpY2F0ZSI6IjAg"
    "PCAyKnBoYXNlIDwgZGVub21pbmF0b3IifSwiZnJhbWVfYm91bmRhcmllcyI6eyJmaXJzdF9yZWpl"
    "Y3RlZF9zZXZlbnRlZW5fZnJhbWVfemVyb19zeW1ib2xfY291bnQiOjEwMzMsImZpcnN0X3R3b19m"
    "cmFtZV96ZXJvX3N5bWJvbF9jb3VudCI6NTcsImxhcmdlc3Rfb25lX2ZyYW1lX3plcm9fc3ltYm9s"
    "X2NvdW50Ijo1NiwibGFyZ2VzdF9zaXh0ZWVuX2ZyYW1lX3plcm9fc3ltYm9sX2NvdW50IjoxMDMy"
    "LCJyZWplY3RlZF9mcmFtZV9jb3VudCI6MTcsInJlamVjdGVkX29jY3VwaWVkX3RvdGFsX3BpeGVs"
    "cyI6Mzk2MDQwOTJ9LCJnb2xkZW5fY2FwdHVyZV9maXh0dXJlX3VzZWQiOmZhbHNlLCJvcmFjbGVf"
    "dXNlZCI6ZmFsc2UsInBhY2tldF92ZWN0b3JzIjp7ImVkZ2VfbWl4Ijp7ImZpbmFsX3NpZ25hbF9m"
    "cmFtZV9pbmRleCI6MCwiZmluYWxfc2lnbmFsX3RvdGFsX2luZGV4Ijo1MjM2NDMsImZpbmFsX3Np"
    "Z25hbF94Ijo0MywiZmluYWxfc2lnbmFsX3kiOjIzOCwiZnJhbWVfY291bnQiOjEsIm9jY3VwaWVk"
    "X3RvdGFsX3BpeGVscyI6NTIzNjQ0LCJwZ21fZnJhbWVfc2hhMjU2IjpbIjdlMjM4YzA4NDdhYWY2"
    "NTYwODZmYjk4NjNkMjRiOTg1MTI1MzcyNzYxOGY5YzlhMWNmNjY5MmY4NWZkN2RjNDEiXSwicmF3"
    "X2ZyYW1lX2JsYWNrX3BpeGVscyI6WzE4NTM5NzZdLCJyYXdfZnJhbWVfc2hhMjU2IjpbIjA1MTdh"
    "YjNiYTY2YWU3NGY5YWNjNDEzOTZjOTg3YzhlZDU3Y2IwMjEyYmU5NTA2YTAzYzcyMzg2ZjY1ZDQ3"
    "MzIiXSwicmF3X2ZyYW1lX3doaXRlX3BpeGVscyI6WzIxOTYyNF0sInNpZ25hbF9waXhlbHMiOjUw"
    "MzcxMiwic2lnbmFsX3NoYTI1NiI6Ijc5YTM4YzM5NDAwYzc4OGZlZTZhYWNhNDY2NTNkMTljODZj"
    "N2JhOWFjZDZmMGYyYTZmOWFlNmIzYjVhODdjMjgiLCJzeW1ib2xfY291bnQiOjUsInN5bWJvbHMi"
    "OnsiZW5jb2RpbmciOiJleHBsaWNpdCIsInZhbHVlcyI6WzAsMSwxMyw2NCwxMjddfSwic3ltYm9s"
    "c19zaGEyNTZfdWludDE2YmUiOiI4ZjgyYjI3NWFkNmRhYjJiNzQyNTk1ODZlMTg3ZjVmYmQwZmY0"
    "MTQzYTc3OGViZmFiYzUxZGFmMjkwY2RmNmM4IiwidGltZWxpbmVfYnl0ZXMiOjI0NzUwMDAsInRp"
    "bWVsaW5lX2NvdW50cyI6eyIwIjo0MDE0MDAsIjEiOjE4NTM5NzYsIjIiOjIxOTYyNH0sInRpbWVs"
    "aW5lX3NoYTI1NiI6ImQ1NzVkNDdmZjA5NDEyMGVhMjA2MWYxOWYwYTFjMzdmYTY3NDZhMmNmMDYw"
    "Njc5NTY2OTliYTNkMDg0ZjIwYjcifSwiZmlyc3RfdHdvX2ZyYW1lIjp7ImZpbmFsX3NpZ25hbF9m"
    "cmFtZV9pbmRleCI6MSwiZmluYWxfc2lnbmFsX3RvdGFsX2luZGV4IjoyNTAwNDc1LCJmaW5hbF9z"
    "aWduYWxfeCI6MTI3NSwiZmluYWxfc2lnbmFsX3kiOjExLCJmcmFtZV9jb3VudCI6Miwib2NjdXBp"
    "ZWRfdG90YWxfcGl4ZWxzIjoyNTAwNDc2LCJwZ21fZnJhbWVfc2hhMjU2IjpbImVhOGZlYmRlNzJl"
    "NzRjZDY2Y2FjNjEwMmQ2MzhhOTY4ZDk2ZGRmMmVkNGJiZmEyZjkyMzhmNjg1MjdiMmRjZTgiLCI3"
    "NWMzOTY3OTcyN2FlZDZkYTcyOGZlN2RmYzkwN2U4ODA2MzRiNWFkNjFmMGE5YTc3NzNiYjAwYTgz"
    "MDRjNTViIl0sInJhd19mcmFtZV9ibGFja19waXhlbHMiOlsxMDM4OTc2LDIwNzExMTNdLCJyYXdf"
    "ZnJhbWVfc2hhMjU2IjpbImNkNzE0ZWJkMzBkM2IyMGI0N2NlNjU3N2JmMWYxNzY3ZGM0YWEyYjM2"
    "YTU2NjdlOGFlNmY1MjQ5YzcyNTM0ODEiLCI2YTNkYTlhMGUwYWRiNWVjYzM2MjIwZjg0MDMyMjUw"
    "ZWY5YzI5ZjcxODhkMDcyZmI0OTY3N2EyYTg3YTUyNmQxIl0sInJhd19mcmFtZV93aGl0ZV9waXhl"
    "bHMiOlsxMDM0NjI0LDI0ODddLCJzaWduYWxfcGl4ZWxzIjoyNDgwNTQ0LCJzaWduYWxfc2hhMjU2"
    "IjoiMGJjZmJkNzE4YWM2MjVmNzBjMDQyM2Q3ZmVlMGJhZjRhYjk0MWI5NjlkNWE5NDBiMzIyZjU4"
    "YmEyOGUyN2Q5YSIsInN5bWJvbF9jb3VudCI6NTcsInN5bWJvbHMiOnsiY291bnQiOjU3LCJlbmNv"
    "ZGluZyI6InJlcGVhdCIsInN5bWJvbCI6MH0sInN5bWJvbHNfc2hhMjU2X3VpbnQxNmJlIjoiODAy"
    "YmJmMTE2N2U5N2UzMzZiYzdlMWQxNTc0NDY2ZGI3NDRjNzAyMWVmZTBmMGZmMDFmZjdlMzUyYzQ0"
    "ZjU2YiIsInRpbWVsaW5lX2J5dGVzIjo0OTUwMDAwLCJ0aW1lbGluZV9jb3VudHMiOnsiMCI6ODAy"
    "ODAwLCIxIjozMTEwMDg5LCIyIjoxMDM3MTExfSwidGltZWxpbmVfc2hhMjU2IjoiZTIzYmQxYTky"
    "YmRmOGJkZDI4ZDZhMmQ3NWExY2UwZDUyOGU1NGUxYmNjYjU1NmRiMzliYjQ5ODcxZDUwZjcyNiJ9"
    "LCJtYXhpbXVtX3NpeHRlZW5fZnJhbWUiOnsiZmluYWxfc2lnbmFsX2ZyYW1lX2luZGV4IjoxNSwi"
    "ZmluYWxfc2lnbmFsX3RvdGFsX2luZGV4IjozOTU2NjA3NSwiZmluYWxfc2lnbmFsX3giOjEyNzUs"
    "ImZpbmFsX3NpZ25hbF95IjoxMTA5LCJmcmFtZV9jb3VudCI6MTYsIm9jY3VwaWVkX3RvdGFsX3Bp"
    "eGVscyI6Mzk1NjYwNzYsInBnbV9mcmFtZV9zaGEyNTYiOlsiZWE4ZmViZGU3MmU3NGNkNjZjYWM2"
    "MTAyZDYzOGE5NjhkOTZkZGYyZWQ0YmJmYTJmOTIzOGY2ODUyN2IyZGNlOCIsImQzN2EwNjE0YWYy"
    "OWY2YjUwNWJlODRiZjU0ODUyYjVlNjQ1MzA1NDQ4MTUwZDRiZTBmMjA2MGI1M2FkOGVkMGUiLCJl"
    "YWE2ZTYxMWQ5MDM0MmEzOTMwYmQ2MTA5MDVhZDkwNmRmZTE4MGJiYTgxZTljNzZjZmQ2OTk1MmYx"
    "ZTY1MGZmIiwiZjU5OGNmOTJlZDExZThhMWUzNzQyNTliODYwMDRhOWIyM2NlYzQ5YzZmZDI5ZWM0"
    "NjZiZTI3MjM5YmQ0ZDhmNSIsIjdiYWQ1M2U4ZTRjZWFmMWQwNjQwNDU1ZmNjZjE5MTliNGNjNDc0"
    "MzU5NjdmMmE0MjdkZGFhMWIwMWZiMzgyN2IiLCI3ZmYxNzU2ZTRkZDZiYWI4M2Q2ZTMyOTgwZTYx"
    "Y2Y2MGEyZGRlOGQ5NWQ0MzZlODIwMWQzMDEyMmMwMTkwMzUxIiwiYTMxMWU4Y2Y4N2M3ZmM4NjAz"
    "NmJkMjIwZGI2YjMxNDFiMWZhMmU1ODg5YWIxZjc3ZjZmZjZjNTg4ZWY3MTY2OCIsIjc1MGViYjQ1"
    "ZGZiMDkzYzc4MjM1YWQ5YzI3ZTMwZWYxOWY3NzZiMmZmZTM0MGJmYWY2YWY1ODNiZjFiOTViNmYi"
    "LCJmMGYzN2IwNjBjZWI1OGQzMDUyNzQzY2NkNDk5MzM2OTMwODc0YTZlM2Q5NjlmNjAwZGQyNDg5"
    "MTA0ZjI0MjgwIiwiOTQ5Mzk5NWRlOTdiMThlMTYxZGY3Mzg3ZjVkNmNmMmRhYWNjNzYwMDg2Y2E1"
    "NTVhOWMyNmIyM2NjNGMxMGFkYyIsImQzOTYwMDExMzJlN2MzOTc1Y2EyYjExZTIwYjFiYjc1M2Y3"
    "Zjk4ZDAyOWVhY2M0ZWFiNTA2ZDgzMTUxMmE4MTQiLCI0ZmQ0MWVkZTAyZWJlYzcwNmY1MjRjMTQy"
    "YWI5YzhiYWViNmVkODE3MGFiNzIwNjNlY2MxZTY0Yzc2ZGRmNWI4IiwiMGFlOWI1ZmE5ODFhMzkw"
    "OTgwY2Y5YjFiODdmMWI3ZDkwZDZmY2I4ZGZlMDFmMTYxZjAzZTRlYzI0ZmZiM2IzYiIsImYyYjVi"
    "YjE4NDYxMjQ4ZDE2MTdmMjFjOTYwYmZiNjU4ZGYzNjgyZWJiN2RiNTczMzY2MTY4ODZiYjI2ZWI3"
    "ZTYiLCJmMGE5YjQ0NTk4YWY4ZjAwZWUyMGJjYjRmYjk5YmM0MGM0N2MzNmNmZjc0ZjQzZTRkZmUx"
    "MjFjYzNjMDYwNGIwIiwiOWM3NWMwYTRiYWI0OGEyZGZhNDUyNjU3MjkzM2M2NGU2NDUyOTIzYTk4"
    "MmFiMzg3OTNhOGY2ZTM2ODFmNWEwYyJdLCJyYXdfZnJhbWVfYmxhY2tfcGl4ZWxzIjpbMTAzODk3"
    "NiwxMDM5MTQ0LDEwMzkxNDQsMTAzOTE2MCwxMDM5MTMxLDEwMzkxNDgsMTAzOTE0MSwxMDM5MTMw"
    "LDEwMzkxNjksMTAzOTE0MCwxMDM5MTUwLDEwMzkxNTEsMTAzOTE0NywxMDM5MTU5LDEwMzkxMzEs"
    "MTAzOTE0Ml0sInJhd19mcmFtZV9zaGEyNTYiOlsiY2Q3MTRlYmQzMGQzYjIwYjQ3Y2U2NTc3YmYx"
    "ZjE3NjdkYzRhYTJiMzZhNTY2N2U4YWU2ZjUyNDljNzI1MzQ4MSIsImUwOTEyM2Q1NzMwZDJlNGMz"
    "ODBjYzU0OGZjMjRhMzFmMzdmYWU2MzM3NjNmYjE5OWU0ODlhNTk5OWI0YmVlNTEiLCI1OTg4NjUw"
    "NGExODM4ZjYzODYxMWQ1NDBiNWFhNWNlZjE0Y2U0MGQ0MjFlZmQ2MDM1OGYwZTcxMGY0NTU0NDUx"
    "IiwiZTY1MjA0ZTQ1ZmFjZDhhZTQ2NjQ2YTAyODI4MDgwNGFkYzM0ODBlNDFjMWJlNmMzMzdkODRh"
    "ZDNkMWVjYWQ1MCIsIjU3ZTdlY2FmYWFmNWVkNDQ2OTVkMWQxZWM2NzlkYTE1ZjY2M2E3NjViMDM5"
    "ZTljMTFjMWIyYzg4OTMxODlhMDkiLCI5MmIzMTAwODBiMGE4NDMxMDI5ZTA1ZjY4YjFkMzg3ZjE3"
    "NmNlYjkyZGQ3MWQxZWViNzhkNmU4OTU2MDQ4OThhIiwiYjA4MDUwYjY5ZDJlYjlhNzRkYzc5YjAx"
    "NDdlNDU0YjFlZWEzOWQxZThmY2Q2ZDlmMDE4ZTJkYjRlMjk3NzFjMiIsIjQwMzJhMzI3NmFhOTcz"
    "OWNiZjhmMWU5ZGNlZWFjZTYwNGM2MzZlNTJiOThhYmZiY2M2MDhmYWI2OGRlYmViYjMiLCJjZmUx"
    "NzE4NGY4YzAwMzMzMWM5OWQ4NDM4ZGI1NzdiMjc1YTI0MWQwM2ZiMjEyMTdlMDA0ZmZlMjk4YjVk"
    "OWY0IiwiMDJmNzU1MDNjZDI4N2ViZDM3MDkwMTA5OTQwYmJmMDgxYzdjNzA5MzA2NzQyNDYyYTgz"
    "ZWY5NDk2YjUyZWU2MCIsIjY2Mjc5MDVhMzFhNmE3M2I4OGNjYWJiNjQyZDZmMGFjYTU2ZDJmNzQ3"
    "NzQ4N2NmY2ExMWExZTBjOWM3Y2UwM2YiLCJjOGIwZDMyNzE0ODllY2QzNzljMzFlZDE2MzQ3MDQw"
    "ZjZhMTgyYWM4MzYwZjM3YmI4MWI0MzgwZDJmZTZkYTVkIiwiMTk5NDYzYTQwNmI4MTZmNDg1Y2E0"
    "NTg3ZDhiODA0Y2M5ZjM3YzA0ZjM2Njc2NWUwODExMjE2ODE5NzMwZGQ1ZiIsIjZiYjQ4YWI4YmQw"
    "Y2IwMzI0MDg4NGY2MzE3MmM1MTkzZmM5NzdkODg5NDRiYmU4YzYyN2Y5ZjBiNjIzMTQ1ZTIiLCJh"
    "YzNiZGM3YWM3NzNkMjkzMjVkYzg4OWZmNmEzNjI0MjU1M2RmMjhlZmUyNWUyMTYzYmY1YWY1YTli"
    "NzYxNjllIiwiY2UwNWNhYTUzNDk5NWJmODIxMmM4YjJmMDgyMjM2ZWEzMjEzMTAzMjNkM2VjMWI4"
    "MTQ1YjBjZTYyNmU4OWFhMiJdLCJyYXdfZnJhbWVfd2hpdGVfcGl4ZWxzIjpbMTAzNDYyNCwxMDM0"
    "NDU2LDEwMzQ0NTYsMTAzNDQ0MCwxMDM0NDY5LDEwMzQ0NTIsMTAzNDQ1OSwxMDM0NDcwLDEwMzQ0"
    "MzEsMTAzNDQ2MCwxMDM0NDUwLDEwMzQ0NDksMTAzNDQ1MywxMDM0NDQxLDEwMzQ0NjksMTAzNDQ1"
    "OF0sInNpZ25hbF9waXhlbHMiOjM5NTQ2MTQ0LCJzaWduYWxfc2hhMjU2IjoiYmM0MmUyOWZmYzhh"
    "OGRhZGFiYTJjZGRiNGY2MDU0MDAxYzdiY2JkNDU0ZDI2OWYzZjU2YjNkZjQxYzliNTc0MyIsInN5"
    "bWJvbF9jb3VudCI6MTAzMiwic3ltYm9scyI6eyJjb3VudCI6MTAzMiwiZW5jb2RpbmciOiJyZXBl"
    "YXQiLCJzeW1ib2wiOjB9LCJzeW1ib2xzX3NoYTI1Nl91aW50MTZiZSI6IjFkODMwYzhhZjRmZjYw"
    "YjFlYzM2MzUwZWEyNWQ5OWM0MjQ3ZDVkMDQwZDhkMmM5YWNiZTI4MDExZWJiOTAzOWUiLCJ0aW1l"
    "bGluZV9ieXRlcyI6Mzk2MDAwMDAsInRpbWVsaW5lX2NvdW50cyI6eyIwIjo2NDIyNDAwLCIxIjox"
    "NjYyNjE2MywiMiI6MTY1NTE0Mzd9LCJ0aW1lbGluZV9zaGEyNTYiOiI4ZGI4YmU5YTBlYTcxNmJk"
    "N2Y5MWVhMTg0YWY1NDRiMmQxZWQ0YjMxYmI2NzNkMTUyYTZmYjdlMmFkMmQ3NjZkIn0sInNpbmds"
    "ZV96ZXJvIjp7ImZpbmFsX3NpZ25hbF9mcmFtZV9pbmRleCI6MCwiZmluYWxfc2lnbmFsX3RvdGFs"
    "X2luZGV4IjozNzE1NzksImZpbmFsX3NpZ25hbF94IjoxOTc5LCJmaW5hbF9zaWduYWxfeSI6MTY4"
    "LCJmcmFtZV9jb3VudCI6MSwib2NjdXBpZWRfdG90YWxfcGl4ZWxzIjozNzE1ODAsInBnbV9mcmFt"
    "ZV9zaGEyNTYiOlsiMzY4NzhhNDNkNzIyOTdjMmIyMGFiNTVkZWMwZTIyZTFiZDMzM2M2ZjZmMTdk"
    "MTJkY2U0ODUwZGYyMjk1MGQyNCJdLCJyYXdfZnJhbWVfYmxhY2tfcGl4ZWxzIjpbMTkyMDIwM10s"
    "InJhd19mcmFtZV9zaGEyNTYiOlsiOWNmMzZkNWZmMmRjOWU5ZmU5MmU2MjJmMWU4OWFiYjdlNWU3"
    "ZGMwYmY1N2E4NjMwODMxMDJjZGY1ODQ2MjU4ZiJdLCJyYXdfZnJhbWVfd2hpdGVfcGl4ZWxzIjpb"
    "MTUzMzk3XSwic2lnbmFsX3BpeGVscyI6MzUxNjQ4LCJzaWduYWxfc2hhMjU2IjoiMGU3MjYxYjU4"
    "NGFmNTA3NGQ2ZWYzNGE3NmViMGRjMzM4YzE4MWM0MmQ4ZGMyN2MyOGUyODRmODFkN2YwNTlmNSIs"
    "InN5bWJvbF9jb3VudCI6MSwic3ltYm9scyI6eyJlbmNvZGluZyI6ImV4cGxpY2l0IiwidmFsdWVz"
    "IjpbMF19LCJzeW1ib2xzX3NoYTI1Nl91aW50MTZiZSI6Ijk2YTI5NmQyMjRmMjg1YzY3YmVlOTNj"
    "MzBmOGEzMDkxNTdmMGRhYTM1ZGM1Yjg3ZTQxMGI3ODYzMGEwOWNmYzciLCJ0aW1lbGluZV9ieXRl"
    "cyI6MjQ3NTAwMCwidGltZWxpbmVfY291bnRzIjp7IjAiOjQwMTQwMCwiMSI6MTkyMDIwMywiMiI6"
    "MTUzMzk3fSwidGltZWxpbmVfc2hhMjU2IjoiOWFmMGQ0MTNkYWIxYzczMGIwNGQwZDFmNzA2Y2E5"
    "ZjBhNWM4MzU2NTg1YTZkYWIzNTVmZGM4ZTdmOWNlMzBiMCJ9fSwicmFzdGVyIjp7ImZyYW1lX3Bp"
    "eGVscyI6MjQ3NTAwMCwicGdtX2hlYWRlcl9hc2NpaSI6IlA1XFxuMTkyMCAxMDgwXFxuMjU1XFxu"
    "IiwicHJlcGFkX3BpeGVscyI6MTk5MzIsInRpbWVsaW5lX2hpZGRlbiI6MCwidGltZWxpbmVfdmlz"
    "aWJsZV9ibGFjayI6MSwidGltZWxpbmVfdmlzaWJsZV93aGl0ZSI6Mn0sInJlbmRlcmVyX2Rlc2Ny"
    "aXB0b3IiOnsiYWN0aXZlX3hfc3RhcnQiOjEzMiwiYWN0aXZlX3lfc3RhcnQiOjksImJhbmR3aWR0"
    "aF9oeiI6NTAwMDAwLCJibGFja19waXhlbCI6MCwiY2VudGVyX2ZyZXF1ZW5jeV9oeiI6OTE1MDAw"
    "MDAwLCJmcmFtZV9yYXRlX2Rlbm9taW5hdG9yIjoxLCJmcmFtZV9yYXRlX251bWVyYXRvciI6NjAs"
    "Im1heGltdW1fZnJhbWVfY291bnQiOjE2LCJuYW1lIjoiZHluYW1pYy1jbGVhci1zb3VyY2UtbGlu"
    "ZWFyLXBoYXNlLTEwODBwNjAtc2Y3LXYxIiwicGl4ZWxfY2xvY2tfaHoiOjE0ODUwMDAwMCwicHJl"
    "YW1ibGVfc3ltYm9scyI6NCwicHJvZmlsZV9pZCI6Miwic2NoZW1hIjoidGVtcGVzdC1sb3JhLmR5"
    "bmFtaWMtcGl4ZWwtcmVuZGVyZXItcHJvZmlsZS52MSIsInNmZF9xdWFydGVyX2NoaXJwcyI6OSwi"
    "c3VwcG9ydGVkX3NwcmVhZGluZ19mYWN0b3IiOjcsInN5bmNfc3ltYm9sc196ZXJvX2Jhc2VkIjpb"
    "OCwxNl0sInRvdGFsX2hlaWdodCI6MTEyNSwidG90YWxfd2lkdGgiOjIyMDAsInZpc2libGVfaGVp"
    "Z2h0IjoxMDgwLCJ2aXNpYmxlX3dpZHRoIjoxOTIwLCJ3aGl0ZV9waXhlbCI6MjU1fSwicmVuZGVy"
    "ZXJfZGVzY3JpcHRvcl9zaGEyNTYiOiIwOGEzYjE5ZTczMmEzMzgyODNhY2NjMDE1OWM4NzEwYTFj"
    "MTdlM2NmNDczMmY0M2UxNDQyYzZjZWQyOTA1YjBkIiwicmVwb3NpdG9yeV9oZWFkIjoiZWU3NjQ1"
    "OTExYTExMTQ1YjkzZjJjMjdjMGE5NTQ1OGYxNTU3OThjZCIsInNjaGVtYSI6InRlbXBlc3QtbG9y"
    "YS5yMmQyaC1jbGVhci1zb3VyY2UtdGVzdC12ZWN0b3JzLnYxIiwic3BvdF9pbmRpY2VzIjpbMCwx"
    "LDIsMywyOTYsMjk3LDI5OCw5NTAzLDk1MDQsMTkwMDcsMTkwMDgsMjg1MTEsMjg1MTIsMzc3MTgs"
    "Mzc3MTksMzgwMTIsMzgwMTMsMzgwMTQsMzgwMTVdLCJzcG90X3ZlY3RvcnMiOnsiZG93bl9rMCI6"
    "eyIwIjowLCIxIjoyNTUsIjE5MDA3IjowLCIxOTAwOCI6MCwiMiI6MjU1LCIyODUxMSI6MCwiMjg1"
    "MTIiOjAsIjI5NiI6MjU1LCIyOTciOjI1NSwiMjk4IjowLCIzIjoyNTUsIjM3NzE4IjoyNTUsIjM3"
    "NzE5IjoyNTUsIjM4MDEyIjoyNTUsIjM4MDEzIjowLCIzODAxNCI6MCwiMzgwMTUiOjAsIjk1MDMi"
    "OjAsIjk1MDQiOjB9LCJkb3duX2sxMjciOnsiMCI6MCwiMSI6MjU1LCIxOTAwNyI6MjU1LCIxOTAw"
    "OCI6MCwiMiI6MjU1LCIyODUxMSI6MCwiMjg1MTIiOjAsIjI5NiI6MjU1LCIyOTciOjAsIjI5OCI6"
    "MCwiMyI6MjU1LCIzNzcxOCI6MjU1LCIzNzcxOSI6MjU1LCIzODAxMiI6MjU1LCIzODAxMyI6MCwi"
    "MzgwMTQiOjAsIjM4MDE1IjowLCI5NTAzIjoyNTUsIjk1MDQiOjI1NX0sInVwX2swIjp7IjAiOjAs"
    "IjEiOjI1NSwiMTkwMDciOjAsIjE5MDA4IjowLCIyIjoyNTUsIjI4NTExIjowLCIyODUxMiI6MCwi"
    "Mjk2IjoyNTUsIjI5NyI6MCwiMjk4IjowLCIzIjoyNTUsIjM3NzE4IjoyNTUsIjM3NzE5IjowLCIz"
    "ODAxMiI6MjU1LCIzODAxMyI6MCwiMzgwMTQiOjAsIjM4MDE1IjowLCI5NTAzIjowLCI5NTA0Ijow"
    "fSwidXBfazEyNyI6eyIwIjowLCIxIjoyNTUsIjE5MDA3IjoyNTUsIjE5MDA4IjowLCIyIjoyNTUs"
    "IjI4NTExIjoyNTUsIjI4NTEyIjoyNTUsIjI5NiI6MjU1LCIyOTciOjAsIjI5OCI6MCwiMyI6MjU1"
    "LCIzNzcxOCI6MjU1LCIzNzcxOSI6MCwiMzgwMTIiOjI1NSwiMzgwMTMiOjAsIjM4MDE0IjowLCIz"
    "ODAxNSI6MCwiOTUwMyI6MCwiOTUwNCI6MH19fQ=="
)
R2D2H_BUNDLE_SHA256 = "f0e8d676a82afe72b47e2e7daea1e50e44c1af3ffe746c6aef8800af31361afe"


def _reference_chirp(
    *,
    symbol: int,
    down: bool,
    profile: DynamicPixelRendererProfile,
) -> bytes:
    chip_count = 1 << profile.supported_spreading_factor
    numerator = profile.pixel_clock_hz * chip_count
    if numerator % profile.bandwidth_hz:
        raise AssertionError("test reference received non-integral chirp")
    chirp_pixels = numerator // profile.bandwidth_hz
    shift_numerator = chirp_pixels * symbol
    if shift_numerator % chip_count:
        raise AssertionError("test reference received non-integral shift")
    shift = shift_numerator // chip_count
    low_hz = profile.center_frequency_hz - profile.bandwidth_hz // 2
    high_hz = profile.center_frequency_hz + profile.bandwidth_hz // 2
    if down:
        low_hz, high_hz = high_hz, low_hz
    low_mod = low_hz % profile.pixel_clock_hz
    high_mod = high_hz % profile.pixel_clock_hz
    denominator = profile.pixel_clock_hz * chirp_pixels
    output = bytearray(chirp_pixels)
    for timer in range(chirp_pixels):
        shifted_position = (shift + timer) % chirp_pixels
        phase_numerator = timer * (
            low_mod * chirp_pixels
            + (high_mod - low_mod) * shifted_position
        )
        phase = phase_numerator % denominator
        output[timer] = 255 if 0 < 2 * phase < denominator else 0
    return bytes(output)


class RendererVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        raw_bundle = base64.b64decode(R2D2H_BUNDLE_BASE64, validate=True)
        if hashlib.sha256(raw_bundle).hexdigest() != R2D2H_BUNDLE_SHA256:
            raise AssertionError("R2D.2H bundle SHA-256 mismatch")
        cls.bundle = json.loads(raw_bundle)
        if canonical_json_bytes(cls.bundle) != raw_bundle:
            raise AssertionError("R2D.2H bundle is not canonical JSON")
        if cls.bundle["repository_head"] != "ee7645911a11145b93f2c27c0a95458f155798cd":
            raise AssertionError("R2D.2H repository HEAD mismatch")
        if cls.bundle["golden_capture_fixture_used"] is not False:
            raise AssertionError("R2D.2H unexpectedly used Golden capture fixture")
        if cls.bundle["oracle_used"] is not False:
            raise AssertionError("R2D.2H unexpectedly used Oracle")

    def _dynamic_envelope(self, symbols: tuple[int, ...], label: str) -> SymbolEnvelope:
        return normalize_dynamic_symbols(
            symbols_zero_based=symbols,
            parameters=DynamicPhyParameters(),
            payload_sha256=hashlib.sha256(label.encode("ascii")).hexdigest(),
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )

    def test_renderer_descriptor_matches_pinned_bundle(self) -> None:
        profile = DynamicPixelRendererProfile()
        self.assertEqual(profile.descriptor(), self.bundle["renderer_descriptor"])
        self.assertEqual(
            profile.descriptor_sha256(),
            self.bundle["renderer_descriptor_sha256"],
        )
        self.assertEqual(
            profile.descriptor_sha256(),
            "08a3b19e732a338283accc0159c8710a1c17e3cf4732f43e1442c6ced2905b0d",
        )

    def test_clear_source_chirp_vectors_and_independent_reference(self) -> None:
        profile = DynamicPixelRendererProfile()
        for name, expected in self.bundle["chirp_vectors"].items():
            direction, raw_symbol = name.split("_k", 1)
            symbol = int(raw_symbol)
            down = direction == "down"
            production = pixel_renderer._render_chirp(
                symbol=symbol,
                down=down,
                profile=profile,
            )
            reference = _reference_chirp(
                symbol=symbol,
                down=down,
                profile=profile,
            )
            self.assertEqual(production, reference, name)
            self.assertEqual(hashlib.sha256(production).hexdigest(), expected["sha256"], name)
            self.assertEqual(production.count(0), expected["black_pixels"], name)
            self.assertEqual(production.count(255), expected["white_pixels"], name)
            self.assertEqual(production.find(b"\xff"), expected["first_white"], name)
            self.assertEqual(production.rfind(b"\xff"), expected["last_white"], name)

        for name, expected_spots in self.bundle["spot_vectors"].items():
            direction, raw_symbol = name.split("_k", 1)
            production = pixel_renderer._render_chirp(
                symbol=int(raw_symbol),
                down=direction == "down",
                profile=profile,
            )
            actual_spots = {
                str(index): production[index]
                for index in self.bundle["spot_indices"]
            }
            self.assertEqual(actual_spots, expected_spots, name)

    def test_packet_vectors(self) -> None:
        for name in (
            "single_zero",
            "edge_mix",
            "first_two_frame",
            "maximum_sixteen_frame",
        ):
            expected = self.bundle["packet_vectors"][name]
            symbol_spec = expected["symbols"]
            if symbol_spec["encoding"] == "explicit":
                symbols = tuple(symbol_spec["values"])
            else:
                symbols = (symbol_spec["symbol"],) * symbol_spec["count"]

            artifact = render_dynamic_envelope(
                envelope=self._dynamic_envelope(symbols, f"r2d2h-{name}")
            )
            manifest = json.loads(artifact.manifest_json)
            for key, value in expected.items():
                if key == "symbols":
                    continue
                self.assertEqual(manifest[key], value, f"{name}:{key}")

            self.assertEqual(
                hashlib.sha256(artifact.timeline_u8).hexdigest(),
                expected["timeline_sha256"],
            )
            self.assertEqual(len(artifact.timeline_u8), expected["timeline_bytes"])
            self.assertEqual(
                {
                    "0": artifact.timeline_u8.count(0),
                    "1": artifact.timeline_u8.count(1),
                    "2": artifact.timeline_u8.count(2),
                },
                expected["timeline_counts"],
            )
            self.assertEqual(
                [hashlib.sha256(frame).hexdigest() for frame in artifact.visible_frames_u8],
                expected["raw_frame_sha256"],
            )
            self.assertEqual(
                [frame.count(0) for frame in artifact.visible_frames_u8],
                expected["raw_frame_black_pixels"],
            )
            self.assertEqual(
                [frame.count(255) for frame in artifact.visible_frames_u8],
                expected["raw_frame_white_pixels"],
            )
            self.assertEqual(
                [hashlib.sha256(frame).hexdigest() for frame in artifact.canonical_pgm_frames],
                expected["pgm_frame_sha256"],
            )
            self.assertFalse(manifest["golden_byte_equality_required"])
            self.assertFalse(manifest["protected_renderer_equivalence_claimed"])
            self.assertFalse(manifest["capture_replay_fixture_used"])
            del artifact
            gc.collect()

    def test_dynamic_render_is_deterministic(self) -> None:
        envelope = self._dynamic_envelope((0, 1, 13, 64, 127), "determinism")
        first = render_dynamic_envelope(envelope=envelope)
        second = render_dynamic_envelope(envelope=envelope)
        self.assertEqual(first, second)

    def test_frame_limit_rejects_before_any_chirp_render(self) -> None:
        rejected_count = self.bundle["frame_boundaries"][
            "first_rejected_seventeen_frame_zero_symbol_count"
        ]
        envelope = self._dynamic_envelope((0,) * rejected_count, "frame-limit")
        with mock.patch.object(
            pixel_renderer,
            "_render_chirp",
            side_effect=AssertionError("chirp render must not run"),
        ):
            with self.assertRaises(ProtocolError):
                render_dynamic_envelope(envelope=envelope)

    def test_profile_boundaries_reject_cross_profile_use(self) -> None:
        capture = normalize_capture_symbols(
            symbols_one_based=(14, 10, 2, 14, 62, 110, 50, 98, 85, 107, 40, 92, 110, 110),
            spreading_factor=7,
            approved_fixture=True,
            fixture_sha256=CAPTURE_GOLDEN_SYMBOL_FIXTURE_SHA256,
        )
        dynamic = self._dynamic_envelope(capture.symbols, "same-numbers")
        with self.assertRaises(ProtocolError):
            render_dynamic_envelope(envelope=capture)

        with self.assertRaises(ProtocolError):
            replay_capture_fixture(envelope=dynamic, fixture_png=b"")


class CaptureReplayTests(unittest.TestCase):
    def _capture_envelope(self) -> SymbolEnvelope:
        return normalize_capture_symbols(
            symbols_one_based=(14, 10, 2, 14, 62, 110, 50, 98, 85, 107, 40, 92, 110, 110),
            spreading_factor=7,
            approved_fixture=True,
            fixture_sha256=CAPTURE_GOLDEN_SYMBOL_FIXTURE_SHA256,
        )

    def _golden_png(self) -> bytes:
        path = (
            Path(__file__).resolve().parents[3]
            / "AttackSamples"
            / "SF7_500kHz_915MHz"
            / "SF7_500kHz_ABC_915MHz_0HzOffset.png"
        )
        return path.read_bytes()

    def test_capture_replay_exact_fixture(self) -> None:
        first = replay_capture_fixture(
            envelope=self._capture_envelope(),
            fixture_png=self._golden_png(),
        )
        second = replay_capture_fixture(
            envelope=self._capture_envelope(),
            fixture_png=self._golden_png(),
        )
        self.assertEqual(first, second)
        self.assertEqual(
            first.source_png_sha256,
            "b35b03f5485f98206dbd3858bdd9d902343a9237273e0b0989f6e5646fabe7f6",
        )
        self.assertEqual(
            hashlib.sha256(first.visible_frame_u8).hexdigest(),
            "641de69d5bf70cd643a12fdec73c401f512ad1b288cdf8c2210f715c020e12c4",
        )
        self.assertEqual(
            hashlib.sha256(first.canonical_pgm).hexdigest(),
            "47357bca7297b24aafe2b642edb0677f88639243b0b149d932830ee29f8915df",
        )
        manifest = json.loads(first.manifest_json)
        self.assertEqual(manifest["generation_mode"], "verified-fixture-replay")
        self.assertFalse(manifest["algorithmic_reconstruction_claimed"])
        self.assertFalse(manifest["transport_capable"])
        self.assertFalse(manifest["hidden_raster_reconstructed"])
        self.assertEqual(manifest["black_pixels"], 1_704_784)
        self.assertEqual(manifest["white_pixels"], 368_816)
        self.assertEqual(manifest["first_white"], [1, 0])
        self.assertEqual(manifest["last_white"], [1051, 384])
        self.assertEqual(
            manifest["white_bounding_box"],
            {"min_x": 0, "max_x": 1919, "min_y": 0, "max_y": 384},
        )

    def test_capture_hash_gate_precedes_png_decode(self) -> None:
        fixture_png = b"X" * 21_884
        with mock.patch.object(
            pixel_renderer,
            "_decode_png_grayscale8",
            side_effect=AssertionError("decoder must not be called"),
        ) as decoder:
            with self.assertRaisesRegex(
                ProtocolError,
                "capture PNG SHA-256 mismatch",
            ):
                replay_capture_fixture(
                    envelope=self._capture_envelope(),
                    fixture_png=fixture_png,
                )
        decoder.assert_not_called()

    def test_capture_rejects_wrong_fixture_or_envelope(self) -> None:
        fixture = self._golden_png()
        corrupted = bytearray(fixture)
        corrupted[-20] ^= 1
        with self.assertRaises(ProtocolError):
            replay_capture_fixture(
                envelope=self._capture_envelope(),
                fixture_png=bytes(corrupted),
            )

        envelope = self._capture_envelope()
        wrong_provenance = replace(
            envelope,
            provenance={
                "fixture_sha256": "0" * 64,
                "approved_fixture": True,
            },
        )
        with self.assertRaises(ProtocolError):
            replay_capture_fixture(
                envelope=wrong_provenance,
                fixture_png=fixture,
            )

    def test_png_decoder_rejects_valid_crc_unknown_critical_chunk(self) -> None:
        fixture = self._golden_png()
        offset = 8
        while offset < len(fixture):
            length = struct.unpack(">I", fixture[offset:offset + 4])[0]
            chunk_type = fixture[offset + 4:offset + 8]
            if chunk_type == b"IDAT":
                break
            offset += 12 + length
        chunk_type = b"ABCD"
        chunk_data = b""
        crc = zlib.crc32(chunk_type)
        crc = zlib.crc32(chunk_data, crc) & 0xFFFFFFFF
        chunk = struct.pack(">I", 0) + chunk_type + struct.pack(">I", crc)
        mutated = fixture[:offset] + chunk + fixture[offset:]
        with self.assertRaises(ProtocolError):
            pixel_renderer._decode_png_grayscale8(mutated)


if __name__ == "__main__":
    unittest.main()
