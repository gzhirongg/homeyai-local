"""
AI service providing insight generation and chat completion.
Uses OpenAI when OPENAI_API_KEY is configured, otherwise falls back to
deterministic mock responses derived from the actual query data.
"""

import os
import json
from typing import Dict, List, Optional, Generator

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

_openai_client = None

def _get_openai():
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def generate_insight(filter_state: Dict, data_summary: Dict) -> Dict:
    """
    Generate an AI executive summary for the current analytics view.
    Returns {"insight": str, "source": "openai"|"mock"}.
    """
    client = _get_openai()

    towns = filter_state.get("towns") or ["All Singapore"]
    flat_types = filter_state.get("flat_types") or ["All types"]
    date_from = filter_state.get("date_from", "earliest")
    date_to = filter_state.get("date_to", "latest")
    summary = data_summary.get("summary", {})
    time_series = data_summary.get("time_series", [])

    if client:
        prompt = _build_insight_prompt(towns, flat_types, date_from, date_to, summary, time_series)
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Singapore real estate analyst. Write concise, data-driven executive summaries."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.7,
            )
            return {"insight": resp.choices[0].message.content, "source": "openai"}
        except Exception as e:
            return {"insight": _mock_insight(towns, flat_types, date_from, date_to, summary, time_series), "source": "mock", "error": str(e)}

    return {"insight": _mock_insight(towns, flat_types, date_from, date_to, summary, time_series), "source": "mock"}


def _build_insight_prompt(towns, flat_types, date_from, date_to, summary, time_series) -> str:
    ts_snippet = ""
    if time_series:
        first_few = time_series[:3]
        last_few = time_series[-3:]
        ts_snippet = f"First periods: {json.dumps(first_few)}\nLast periods: {json.dumps(last_few)}"

    return f"""Analyze this HDB resale market data and write a 3-5 sentence executive summary.

Filters applied:
- Towns: {', '.join(towns)}
- Flat types: {', '.join(flat_types)}
- Period: {date_from} to {date_to}

Summary statistics:
- Total transactions: {summary.get('total', 0):,}
- Average price: S${summary.get('avg_price', 0):,}
- Average PSF: S${summary.get('avg_psf', 0)}
- Price range: S${summary.get('min_price', 0):,} – S${summary.get('max_price', 0):,}

Time series (sample):
{ts_snippet}

Cover: (1) key price trend direction, (2) notable volume or price shifts, (3) one actionable insight for buyers/sellers."""


def _mock_insight(towns, flat_types, date_from, date_to, summary, time_series) -> str:
    total = summary.get("total", 0)
    avg_price = summary.get("avg_price", 0)
    avg_psf = summary.get("avg_psf", 0)
    town_str = ", ".join(towns[:3]) if towns else "all towns"
    ft_str = ", ".join(flat_types[:3]) if flat_types else "all flat types"

    trend_direction = "remained stable"
    if len(time_series) >= 2:
        first_price = time_series[0].get("avg_price", 0)
        last_price = time_series[-1].get("avg_price", 0)
        if first_price > 0:
            change_pct = ((last_price - first_price) / first_price) * 100
            if change_pct > 5:
                trend_direction = f"increased by {change_pct:.1f}%"
            elif change_pct < -5:
                trend_direction = f"decreased by {abs(change_pct):.1f}%"

    return (
        f"Based on {total:,} transactions in {town_str} for {ft_str} "
        f"from {date_from} to {date_to}, the average resale price {trend_direction} "
        f"to S${avg_price:,} (S${avg_psf:.0f} PSF). "
        "These are historical averages for the selected records; they do not establish "
        "a national median, investment recommendation or forecast."
    )


# ---------------------------------------------------------------------------
# Chat completion with tool calling
# ---------------------------------------------------------------------------

CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": "Query HDB resale transactions with filters. Returns time series, summary stats, and breakdowns by town and flat type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "towns": {"type": "array", "items": {"type": "string"}, "description": "Towns to filter (e.g. BEDOK, TAMPINES)"},
                    "flat_types": {"type": "array", "items": {"type": "string"}, "description": "Flat types (e.g. 3 ROOM, 4 ROOM, 5 ROOM)"},
                    "date_from": {"type": "string", "description": "Start date YYYY-MM"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM"},
                    "price_min": {"type": "integer", "description": "Minimum price"},
                    "price_max": {"type": "integer", "description": "Maximum price"},
                    "group_by": {"type": "string", "enum": ["month", "year", "quarter"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_district_analytics",
            "description": "Get detailed analytics for a specific town/district including historical trend and notable projects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district_name": {"type": "string", "description": "Town name (e.g. BEDOK)"},
                },
                "required": ["district_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": "Instruct the frontend to render an interactive chart in the chat. Use after retrieving data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {"type": "string", "enum": ["line", "bar", "area"], "description": "Chart type"},
                    "title": {"type": "string"},
                    "data": {"type": "array", "items": {"type": "object"}, "description": "Array of data points"},
                    "x_key": {"type": "string", "description": "Key for X axis"},
                    "y_key": {"type": "string", "description": "Key for Y axis"},
                    "y_label": {"type": "string", "description": "Label for Y axis"},
                },
                "required": ["chart_type", "title", "data", "x_key", "y_key"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are HomeyAI, a Singapore HDB resale market analyst assistant.

You have access to a database of HDB resale transactions spanning multiple years.
You can query transactions with filters, get district analytics, and generate charts.

Guidelines:
- Always use tools to fetch real data before answering quantitative questions
- When showing trends, generate a chart for visual clarity
- Cite specific numbers from the data
- If data is insufficient, say so honestly
- For flat types, use uppercase: "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"
- For towns, use uppercase: "BEDOK", "TAMPINES", "CLEMENTI", etc.
- HDB leases are 99 years from commencement date
- PSF = Price per Square Foot = resale_price / (floor_area_sqm * 10.764)"""


def execute_tool(name: str, arguments: Dict) -> Dict:
    """Execute a tool call against our analytics services."""
    from services import analytics_service

    if name == "query_transactions":
        return analytics_service.query_transactions(**arguments)
    elif name == "get_district_analytics":
        return analytics_service.get_district_analytics(arguments["district_name"])
    elif name == "generate_chart":
        return {"type": "chart", **arguments}
    return {"error": f"Unknown tool: {name}"}


def chat_completion(messages: List[Dict], analytics_context: Optional[Dict] = None) -> Generator[Dict, None, None]:
    """
    Process a chat conversation. Yields message blocks:
    - {"type": "text", "content": "..."} for text chunks
    - {"type": "chart", ...} for chart data
    - {"type": "tool_call", "name": "...", "result": {...}} for transparency
    - {"type": "done"} when finished
    """
    client = _get_openai()

    system_content = SYSTEM_PROMPT
    if analytics_context:
        ctx_parts = []
        if analytics_context.get("filters"):
            ctx_parts.append(f"Active filters: {json.dumps(analytics_context['filters'])}")
        if analytics_context.get("summary"):
            ctx_parts.append(f"Current data summary: {json.dumps(analytics_context['summary'])}")
        if analytics_context.get("report_title"):
            ctx_parts.append(f"Related report: {analytics_context['report_title']}")
        if ctx_parts:
            system_content += "\n\n--- ANALYTICS CONTEXT ---\n" + "\n".join(ctx_parts) + "\n--- END CONTEXT ---\nUse this context to provide relevant, data-aware answers without requiring additional tool calls when the data is already available."

    full_messages = [{"role": "system", "content": system_content}] + messages

    if client:
        yield from _openai_chat(client, full_messages)
    else:
        yield from _mock_chat(messages)


def _openai_chat(client, messages: List[Dict]) -> Generator[Dict, None, None]:
    """Real OpenAI chat with tool calling loop."""
    MAX_TOOL_ROUNDS = 5

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=CHAT_TOOLS,
            temperature=0.7,
            max_tokens=1000,
        )

        choice = resp.choices[0]

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message.model_dump())
            for tc in choice.message.tool_calls:
                args = json.loads(tc.function.arguments)
                result = execute_tool(tc.function.name, args)

                if tc.function.name == "generate_chart":
                    yield {"type": "chart", **result}

                yield {"type": "tool_call", "name": tc.function.name, "arguments": args}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                })
        else:
            content = choice.message.content or ""
            if content:
                yield {"type": "text", "content": content}
            break

    yield {"type": "done"}


def _mock_chat(messages: List[Dict]) -> Generator[Dict, None, None]:
    """Mock chat that parses the user query and returns data-driven responses."""
    from services import analytics_service

    last_msg = messages[-1].get("content", "") if messages else ""
    lower = last_msg.lower()

    towns_mentioned = []
    for town in analytics_service.get_filter_options().get("towns", []):
        if town.lower() in lower:
            towns_mentioned.append(town)

    flat_types_mentioned = []
    for ft in ["1 ROOM", "2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE", "MULTI-GENERATION"]:
        ft_patterns = [ft.lower(), ft.lower().replace(" ", "-"), ft.lower().replace(" room", "-room")]
        if any(p in lower for p in ft_patterns):
            flat_types_mentioned.append(ft)

    data = analytics_service.query_transactions(
        towns=towns_mentioned or None,
        flat_types=flat_types_mentioned or None,
        group_by="year",
    )

    summary = data.get("summary", {})
    ts = data.get("time_series", [])

    town_label = ", ".join(towns_mentioned) if towns_mentioned else "all towns in Singapore"
    ft_label = ", ".join(flat_types_mentioned) if flat_types_mentioned else "all flat types"

    if ts:
        yield {
            "type": "chart",
            "chart_type": "line",
            "title": f"Price Trend — {town_label} ({ft_label})",
            "data": [{"period": p["period"], "avg_price": p["avg_price"]} for p in ts],
            "x_key": "period",
            "y_key": "avg_price",
            "y_label": "Average Price (S$)",
        }

    trend_note = ""
    if len(ts) >= 2:
        first_p = ts[0]["avg_price"]
        last_p = ts[-1]["avg_price"]
        if first_p > 0:
            change = ((last_p - first_p) / first_p) * 100
            trend_note = f"Prices have {'increased' if change > 0 else 'decreased'} by {abs(change):.1f}% over this period. "

    content = (
        f"Here's what the data shows for **{ft_label}** in **{town_label}**:\n\n"
        f"- **Total transactions**: {summary.get('total', 0):,}\n"
        f"- **Average price**: S${summary.get('avg_price', 0):,}\n"
        f"- **Average PSF**: S${summary.get('avg_psf', 0):.0f}\n"
        f"- **Price range**: S${summary.get('min_price', 0):,} – S${summary.get('max_price', 0):,}\n\n"
        f"{trend_note}"
        f"The chart above shows the yearly price trend. "
    )

    if not OPENAI_API_KEY:
        content += "\n\n*Note: Connect an OpenAI API key for deeper conversational analysis.*"

    yield {"type": "text", "content": content}
    yield {"type": "done"}
