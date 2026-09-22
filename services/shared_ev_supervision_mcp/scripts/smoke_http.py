"""Run a privacy-safe Streamable HTTP smoke test against the MCP service."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    parser.add_argument("--start-date", default="2026-08-22")
    parser.add_argument("--end-date", default="2026-09-20")
    parser.add_argument("--expected-base-url")
    return parser.parse_args()


def _structured(result: CallToolResult, tool_name: str) -> Mapping[str, Any]:
    if result.isError:
        details = "; ".join(block.text for block in result.content if getattr(block, "type", None) == "text")
        suffix = f": {details}" if details else ""
        raise RuntimeError(f"{tool_name} returned a tool error{suffix}")
    payload = result.structuredContent
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"{tool_name} did not return structured output")
    return payload


async def _run(args: argparse.Namespace) -> None:
    async with (
        httpx.AsyncClient(trust_env=False, timeout=120.0) as http_client,
        streamable_http_client(args.url, http_client=http_client) as (read_stream, write_stream, _),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        metadata = _structured(await session.call_tool("get_api_metadata"), "get_api_metadata")
        if args.expected_base_url and metadata.get("base_url") != args.expected_base_url:
            raise RuntimeError("MCP service is not using the expected Java Base URL")

        suppliers = _structured(await session.call_tool("list_suppliers"), "list_suppliers")
        realtime = _structured(
            await session.call_tool("get_helmet_realtime_metrics", arguments={}),
            "get_helmet_realtime_metrics",
        )
        date_arguments = {"start_date": args.start_date, "end_date": args.end_date}
        helmet = _structured(
            await session.call_tool("get_helmet_statistics", arguments=date_arguments),
            "get_helmet_statistics",
        )
        cases = _structured(
            await session.call_tool(
                "search_cases",
                arguments={**date_arguments, "page": 1, "page_size": 1},
            ),
            "search_cases",
        )
        patrol = _structured(
            await session.call_tool(
                "search_patrol_results",
                arguments={**date_arguments, "page": 1, "page_size": 20},
            ),
            "search_patrol_results",
        )
        orders = _structured(
            await session.call_tool("get_order_summary", arguments={"page": 1, "page_size": 20}),
            "get_order_summary",
        )
        question_types = _structured(
            await session.call_tool("list_case_question_types"),
            "list_case_question_types",
        )

        case_detail: Mapping[str, Any] | None = None
        grid_location: Mapping[str, Any] | None = None
        case_items = cases.get("items")
        if isinstance(case_items, list) and case_items and isinstance(case_items[0], Mapping):
            case_id = case_items[0].get("case_id")
            source_table = case_items[0].get("source_table")
            if isinstance(case_id, int) and isinstance(source_table, str):
                case_detail = _structured(
                    await session.call_tool(
                        "get_case_detail",
                        arguments={"case_id": case_id, "source_table": source_table},
                    ),
                    "get_case_detail",
                )
                longitude = case_detail.get("longitude")
                latitude = case_detail.get("latitude")
                if isinstance(longitude, (int, float)) and isinstance(latitude, (int, float)):
                    grid_location = _structured(
                        await session.call_tool(
                            "locate_case_grid",
                            arguments={"longitude": longitude, "latitude": latitude},
                        ),
                        "locate_case_grid",
                    )

        patrol_detail: Mapping[str, Any] | None = None
        section_totals: dict[str, int | None] = {}
        section_candidates_skipped: dict[str, int] = {}
        patrol_items = patrol.get("items")
        if isinstance(patrol_items, list):
            result_ids = [
                item["result_id"] for item in patrol_items if isinstance(item, Mapping) and isinstance(item.get("result_id"), str)
            ]
            if result_ids:
                patrol_detail = _structured(
                    await session.call_tool("get_patrol_result", arguments={"result_id": result_ids[0]}),
                    "get_patrol_result",
                )
                for section in (
                    "area_summary",
                    "supplier_summary",
                    "vehicles",
                    "grids",
                    "parking_areas",
                    "mac_devices",
                    "data_push",
                    "abnormal_statistics",
                ):
                    last_call: CallToolResult | None = None
                    section_candidates_skipped[section] = 0
                    for result_id in result_ids:
                        last_call = await session.call_tool(
                            "query_patrol_result_section",
                            arguments={"result_id": result_id, "section": section, "page": 1, "page_size": 1},
                        )
                        if last_call.isError:
                            section_candidates_skipped[section] += 1
                            continue
                        section_result = _structured(last_call, f"query_patrol_result_section[{section}]")
                        total = section_result.get("total")
                        section_totals[section] = total if isinstance(total, int) else None
                        break
                    if section not in section_totals and last_call is not None:
                        _structured(last_call, f"query_patrol_result_section[{section}]")

    summary = {
        "base_url": metadata["base_url"],
        "tool_count": len(tools.tools),
        "supplier_count": suppliers.get("total"),
        "helmet_realtime_ok": isinstance(realtime.get("helmet_total"), int),
        "helmet_trend_points": len(helmet.get("wearing_trend", [])),
        "case_total": cases.get("total"),
        "case_items_returned": len(cases.get("items", [])),
        "case_detail_ok": case_detail is not None,
        "case_handle_count": len(case_detail.get("handles", [])) if case_detail else None,
        "case_question_type_count": len(question_types.get("items", [])),
        "case_grid_lookup_ok": grid_location is not None,
        "patrol_total": patrol.get("total"),
        "patrol_items_returned": len(patrol.get("items", [])),
        "patrol_detail_ok": patrol_detail is not None,
        "patrol_section_totals": section_totals,
        "patrol_section_candidates_skipped": section_candidates_skipped,
        "order_items_returned": len(orders.get("items", [])),
        "order_fallback_applied": orders.get("window", {}).get("fallback_applied"),
        "order_effective_start_date": orders.get("window", {}).get("effective_start_date"),
        "order_effective_end_date": orders.get("window", {}).get("effective_end_date"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    main()
