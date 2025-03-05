import re
from typing import List, Tuple, cast

from selectolax.lexbor import LexborHTMLParser, LexborNode


def parse_multiroot_html(html: str) -> Tuple[LexborNode, List[LexborNode]]:
    # NOTE: HTML / XML MUST have a single root. So, to support multiple
    # top-level elements, we wrap them in a dummy singular root.
    parser = LexborHTMLParser(f"<root>{html}</root>")

    # Get all contents of the root
    root_elem = parser.css_first("root")
    elems = [*root_elem.iter()] if root_elem else []
    return cast(LexborNode, root_elem), elems


def serialize_multiroot_html(root: LexborNode) -> str:
    # Remove the top-level `<root></root>` that wraps the actual content,
    # introduced by `parse_multiroot_html`.
    return root.html[6:-7]  # type: ignore[index]


def parse_node(html: str) -> LexborNode:
    parser = LexborHTMLParser(html)
    # NOTE: The parser automatically places <style> tags inside <head>
    # while <script> tags are inside <body>.
    return parser.body.child or parser.head.child  # type: ignore[union-attr, return-value]


def set_boolean_attribute(node: LexborNode, attr: str, value: bool) -> None:
    if value:
        # NOTE: Empty string as value to signify a truthy boolean attribute
        #       See https://developer.mozilla.org/en-US/docs/Glossary/Boolean/HTML
        node.attrs[attr] = ""  # type: ignore[index]
    else:
        if attr in node.attrs:  # type: ignore[operator]
            del node.attrs[attr]  # type: ignore[attr-defined]


# NOTE: While Selectolax offers way to insert a node before or after
# a current one, it doesn't allow to insert one node into another.
# See https://github.com/rushter/selectolax/issues/126
def html_insert_before_end(html: str, insert_html: str) -> str:
    regex = re.compile(r"<\/\w+>$")
    return regex.sub(
        lambda m: insert_html + m[0],
        html.strip(),
    )


def insert_before_end(node: LexborNode, insertee: LexborNode) -> None:
    new_node_html = html_insert_before_end(node.html or "", insertee.html or "")
    new_node = parse_node(new_node_html)
    node.replace_with(new_node)  # type: ignore[arg-type]
