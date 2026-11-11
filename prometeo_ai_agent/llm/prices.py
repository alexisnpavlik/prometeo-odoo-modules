"""Precios conocidos de modelos de chat, en USD por millón de tokens (entrada, salida).

Ninguna API los informa: se cargan acá y el administrador los edita en Odoo.
Consultado en las páginas oficiales de precios el 2026-11-11. Tramo de prompts
cortos (Gemini <= 200k tokens, Claude Haiku 5.5 <= 100k tokens).
Clave: (tipo de proveedor, prefijo del id de modelo). Gana el prefijo más largo.
"""

KNOWN_PRICES = {
    # Anthropic
    ("anthropic", "claude-fable-5-2"): (8.0, 40.0),
    ("anthropic", "claude-fable-5-1"): (10.0, 50.0),
    ("anthropic", "claude-fable-5"): (10.0, 50.0),
    ("anthropic", "claude-opus-5-5"): (4.0, 20.0),
    ("anthropic", "claude-opus-5"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-8"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-7"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-6"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-5"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-1"): (15.0, 75.0),
    ("anthropic", "claude-opus-4"): (15.0, 75.0),
    ("anthropic", "claude-sonnet-5-5"): (2.0, 10.0),
    ("anthropic", "claude-sonnet-5"): (2.0, 10.0),
    ("anthropic", "claude-sonnet-4-6"): (3.0, 15.0),
    ("anthropic", "claude-sonnet-4-5"): (3.0, 15.0),
    ("anthropic", "claude-sonnet-4"): (3.0, 15.0),
    ("anthropic", "claude-haiku-5-5"): (0.10, 0.50),
    ("anthropic", "claude-haiku-4-5"): (1.0, 5.0),
    # OpenAI
    ("openai", "gpt-6-astra"): (10.0, 50.0),
    ("openai", "gpt-6.1-sol"): (2.0, 10.0),
    ("openai", "gpt-6.1-terra"): (1.0, 5.0),
    ("openai", "gpt-6-luna"): (0.10, 0.50),
    ("openai", "gpt-6-sol"): (2.0, 10.0),
    ("openai", "gpt-5.6-sol"): (4.0, 20.0),
    ("openai", "gpt-5.6-terra"): (2.0, 12.0),
    ("openai", "gpt-5.6-luna"): (0.20, 1.20),
    ("openai", "gpt-5.5-pro"): (30.0, 180.0),
    ("openai", "gpt-5.5"): (5.0, 30.0),
    ("openai", "gpt-5.4-pro"): (30.0, 180.0),
    ("openai", "gpt-5.4-mini"): (0.75, 4.50),
    ("openai", "gpt-5.4-nano"): (0.20, 1.25),
    ("openai", "gpt-5.4"): (2.50, 15.0),
    ("openai", "gpt-5.2-pro"): (21.0, 168.0),
    ("openai", "gpt-5.2"): (1.75, 14.0),
    ("openai", "gpt-5.1"): (1.25, 10.0),
    ("openai", "gpt-5-pro"): (15.0, 120.0),
    ("openai", "gpt-5-mini"): (0.25, 2.0),
    ("openai", "gpt-5-nano"): (0.05, 0.40),
    ("openai", "gpt-5"): (1.25, 10.0),
    ("openai", "gpt-4.1-mini"): (0.40, 1.60),
    ("openai", "gpt-4.1"): (2.0, 8.0),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", "gpt-4o"): (2.50, 10.0),
    ("openai", "o3-pro"): (20.0, 80.0),
    ("openai", "o3"): (2.0, 8.0),
    # Google
    ("google", "gemini-4-carbon"): (2.0, 10.0),
    ("google", "gemini-4-argon"): (2.0, 10.0),
    ("google", "gemini-3.8-flash"): (0.75, 3.75),
    ("google", "gemini-3.6-flash"): (0.75, 3.75),
    ("google", "gemini-3.5-flash-lite"): (0.30, 2.50),
    ("google", "gemini-3.1-flash-lite"): (0.25, 1.50),
    ("google", "gemini-3.1-pro"): (2.0, 12.0),
    ("google", "gemini-3-flash"): (0.50, 3.0),
    ("google", "gemini-2.5-pro"): (1.25, 10.0),
    ("google", "gemini-2.5-flash-lite"): (0.10, 0.40),
    ("google", "gemini-2.5-flash"): (0.30, 2.50),
}


def lookup_price(provider_type, model_name):
    """Precio (entrada, salida) del prefijo más largo que coincide, o None."""
    best = None
    for (ptype, prefix), price in KNOWN_PRICES.items():
        if ptype == provider_type and model_name.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, price)
    return best[1] if best else None
