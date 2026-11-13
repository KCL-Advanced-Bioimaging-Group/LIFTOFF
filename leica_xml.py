"""Parse Leica metadata without DTDs or entity declarations."""

import re
import xml.etree.ElementTree as ET

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

MAX_XML_CHARACTERS = 32 * 1024 * 1024
_DECLARATIONS = re.compile(r"<!--|<!\[CDATA\[|<!DOCTYPE\b|<!ENTITY\b")


def reject_xml_declarations(text: str) -> None:
    """Check whole headers without requiring strict Leica XML syntax."""
    if len(text) > MAX_XML_CHARACTERS:
        raise ET.ParseError("XML metadata exceeds the supported size limit")
    opaque_until = 0
    for match in _DECLARATIONS.finditer(text):
        if match.start() < opaque_until:
            continue
        if match.group() in ("<!--", "<![CDATA["):
            end = text.find(
                "-->" if match.group() == "<!--" else "]]>", match.end()
            )
            opaque_until = len(text) if end < 0 else end + 3
        else:
            raise ET.ParseError(
                "XML DTDs and entity declarations are not supported"
            )


def parse_xml(text: str) -> ET.Element:
    """Parse ordinary XML and reject unsupported DTD features."""
    reject_xml_declarations(text)
    try:
        return ElementTree.fromstring(
            text, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except DefusedXmlException as error:
        raise ET.ParseError(
            "XML DTDs and entity declarations are not supported"
        ) from error
