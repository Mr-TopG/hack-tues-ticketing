from io import BytesIO

import segno


def render_qr_svg(value):
    output = BytesIO()
    qr_code = segno.make_qr(
        value,
        error="M",
    )
    qr_code.save(
        output,
        kind="svg",
        scale=6,
        border=4,
        dark="#000000",
        light="#ffffff",
        xmldecl=False,
    )
    return output.getvalue()
