"""Görsel açıklama servisi: Groq Vision ile grafik/figure okuma (Faz 3).

Görseller base64'e encode edilip LangChain ChatGroq formatında (HumanMessage
+ image_url bloğu) modele gönderilir; prompt görsel tipine göre seçilir.
Açıklamalar embedding için İngilizce istenir (bge-small-en + İngilizce
10-K içeriğiyle tutarlılık).
"""

import base64
from pathlib import Path

from langchain_core.messages import HumanMessage

from app.core.llm import get_vision_llm

# Görsel tipine göre prompt stratejisi.
PROMPTS: dict[str, str] = {
    "chart": (
        "What data does this chart show? What are the axes? What is the main "
        "trend? Read out the specific numeric values if visible. Summarize in "
        "2-3 sentences."
    ),
    "figure": (
        "What does this figure show? What are the main objects and labels? "
        "Summarize in 2-3 sentences."
    ),
    "logo": "Describe this logo (mention the brand name if visible). 1 sentence is enough.",
}

# Tip tanınmıyorsa genel tanım istenecek.
GENERIC_PROMPT = "Describe this image briefly in 2-3 sentences."


class VisionService:
    """Görselleri Groq Vision'a gönderip metin açıklaması üretir."""

    async def describe_image(self, image_path: str | Path, image_type: str) -> str:
        """Görseli Groq Vision'a gönderir, açıklama döner.

        image_type: "chart" | "figure" | "logo" | "unknown" — tip bilinmiyorsa
        genel tanım promptu kullanılır. Görsel bulunamazsa veya API hatasında
        istisna yükseltir (çağıran taraf fallback uygular).
        """
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Görsel bulunamadı: {path}")
        prompt = PROMPTS.get(image_type, GENERIC_PROMPT)
        data_url = self._to_data_url(path)

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )
        response = await get_vision_llm().ainvoke([message])
        content = response.content
        if isinstance(content, list):  # bazı modeller blok listesi döner
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return str(content).strip()

    @staticmethod
    def _to_data_url(path: Path) -> str:
        """Dosyayı base64 data URL'ine çevirir (mime uzantıdan)."""
        mime = "image/png" if path.suffix.lower() in (".png",) else "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
