import asyncio
import re
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from pipeline.adapters.base import (
    CivilViewAdapter,
    RawSheriffSale,
)

from pipeline.parse_sale_description import (
    parse_sale_description,
    parsed_to_json_dict,
)

class MonmouthCivilViewAdapter(CivilViewAdapter):
    COUNTY_NAME = "Monmouth"
    COUNTY_ID = 8

    SEARCH_URL = (
        "https://salesweb.civilview.com/"
        "Sales/SalesSearch?countyId=8"
    )

    SHERIFF_NUMBER_PATTERN = re.compile(
        r"\bFOR-\d+\b",
        re.IGNORECASE,
    )

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._records_by_id: Dict[str, RawSheriffSale] = {}
        self._cookies = httpx.Cookies()

    async def fetch_sale_index(self) -> List[str]:
        """
        Download the Monmouth CivilView listing page and parse
        all sheriff-sale records.
        """

        html = await self._download_page()
        soup = BeautifulSoup(html, "html.parser")

        table = self._find_sales_table(soup)

        if table is None:
            self._save_debug_html(
                html,
                "civilview_listing_debug.html",
            )

            raise RuntimeError(
                "CivilView sales table was not found. "
                "The page was saved as "
                "civilview_listing_debug.html."
            )

        header_map = self._get_header_map(table)

        print("Detected CivilView columns:", header_map)

        rows = table.find_all("tr")

        print(f"Found {len(rows)} HTML table rows.")

        self._records_by_id.clear()

        for row in rows:
            record = self._parse_row(
                row=row,
                header_map=header_map,
            )

            if record is not None:
                self._records_by_id[
                    record.sheriff_number
                ] = record

        if not self._records_by_id:
            self._save_debug_html(
                html,
                "civilview_listing_debug.html",
            )
            return []

        print(
            f"Parsed {len(self._records_by_id)} listing records."
        )
        print("Downloading detail pages...")

        headers = {
            **self._browser_headers(),
            "Referer": self.SEARCH_URL,
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            cookies=self._cookies,
        ) as client:
            total = len(self._records_by_id)

            for position, (
                sheriff_number,
                record,
            ) in enumerate(
                list(self._records_by_id.items()),
                start=1,
            ):
                try:
                    enriched = (
                        await self.enrich_record_from_detail_page(
                            client=client,
                            record=record,
                        )
                    )

                    self._records_by_id[
                        sheriff_number
                    ] = enriched

                    print(
                        f"[{position}/{total}] "
                        f"{sheriff_number} | "
                        f"{enriched.status} | "
                        f"judgment={getattr(enriched, 'judgment_amount', None)} | "
                        f"upset={enriched.upset_price}"
                    )

                except Exception as exc:
                    record.raw_payload[
                        "detail_page_error"
                    ] = str(exc)

                    print(
                        f"[{position}/{total}] "
                        f"{sheriff_number} | "
                        f"detail error: {exc}"
                    )

                await asyncio.sleep(0.25)

        return list(self._records_by_id.keys())

    async def fetch_sale(
        self,
        source_id: str,
    ) -> RawSheriffSale:
        """
        Return one record previously parsed from the listing.
        """

        if not self._records_by_id:
            await self.fetch_sale_index()

        normalized_id = source_id.strip().upper()

        record = self._records_by_id.get(normalized_id)

        if record is None:
            raise KeyError(
                f"Sheriff sale {source_id!r} was not found."
            )

        return record

    async def _download_page(self) -> str:
        """
        Download the listing page and preserve response cookies.
        """

        headers = self._browser_headers()

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            cookies=self._cookies,
        ) as client:
            response = await client.get(self.SEARCH_URL)
            response.raise_for_status()

            self._cookies.update(response.cookies)

        print(
            "CivilView response:",
            response.status_code,
            f"{len(response.text)} characters",
        )

        return response.text

    async def enrich_record_from_detail_page(
        self,
        client: httpx.AsyncClient,
        record: RawSheriffSale,
    ) -> RawSheriffSale:
        """
        Download one CivilView detail page, preserve its complete
        visible text and HTML, and parse financial/property fields.
        """

        if not record.source_url:
            return record

        if "/Sales/SaleDetails" not in record.source_url:
            record.raw_payload[
                "detail_page_skipped"
            ] = "No SaleDetails URL was found."
            return record

        response = await client.get(record.source_url)
        response.raise_for_status()
        self._cookies.update(response.cookies)

        final_url = str(response.url)

        if "/Sales/SaleDetails" not in final_url:
            record.raw_payload[
                "detail_page_redirected_to"
            ] = final_url
            return record

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        structured_fields = self._extract_detail_fields(
            soup
        )

        for element in soup(
            ["script", "style", "noscript", "svg"]
        ):
            element.decompose()

        description_text = soup.get_text(
            "\n",
            strip=True,
        )

        parsed = parse_sale_description(
            description_text
        )
        parsed_dict = parsed_to_json_dict(parsed)

        upset_price = (
            getattr(
                parsed,
                "estimated_upset_price",
                None,
            )
            or getattr(
                parsed,
                "alternate_upset_price",
                None,
            )
            or self._find_money_field(
                structured_fields,
                [
                    "estimated upset",
                    "approximate upset",
                    "upset price",
                    "upset amount",
                ],
            )
        )

        judgment_amount = (
            getattr(
                parsed,
                "judgment_amount",
                None,
            )
            or self._find_money_field(
                structured_fields,
                [
                    "judgment amount",
                    "final judgment",
                    "approximate judgment",
                    "judgment",
                ],
            )
        )

        plaintiff_attorney = (
            getattr(
                parsed,
                "attorney_name",
                None,
            )
            or self._find_text_field(
                structured_fields,
                [
                    "plaintiff attorney",
                    "attorney",
                ],
            )
        )

        court_case_number = (
            getattr(
                parsed,
                "docket_number",
                None,
            )
            or self._find_text_field(
                structured_fields,
                [
                    "court case",
                    "case number",
                    "docket number",
                    "docket",
                ],
            )
        )

        block = (
            getattr(parsed, "block", None)
            or self._find_text_field(
                structured_fields,
                ["block"],
            )
        )

        lot = (
            getattr(parsed, "lot", None)
            or self._find_text_field(
                structured_fields,
                ["lot"],
            )
        )

        qualifier = (
            getattr(parsed, "qualifier", None)
            or self._find_text_field(
                structured_fields,
                ["qualifier"],
            )
        )

        raw_payload = {
            **record.raw_payload,
            "description_text": description_text,
            "description_html": response.text,
            "description_source_url": final_url,
            "parsed_description": parsed_dict,
            "detail_fields": structured_fields,
        }

        return replace(
            record,
            upset_price=upset_price,
            judgment_amount=judgment_amount,
            plaintiff_attorney=plaintiff_attorney,
            court_case_number=court_case_number,
            block=block,
            lot=lot,
            qualifier=qualifier,
            detail_fields=structured_fields,
            raw_payload=raw_payload,
        )


    async def enrich_sale_detail(
        self,
        sale: RawSheriffSale,
    ) -> RawSheriffSale:
        """
        Attempt to download and parse one sale-detail page.

        CivilView may redirect detail URLs to the homepage when
        the required site session is unavailable. In that case,
        the original listing record is returned unchanged.
        """

        if not sale.source_url:
            return sale

        if "/Sales/SaleDetails" not in sale.source_url:
            return sale

        headers = {
            **self._browser_headers(),
            "Referer": self.SEARCH_URL,
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            cookies=self._cookies,
        ) as client:
            response = await client.get(sale.source_url)
            response.raise_for_status()

            self._cookies.update(response.cookies)

        final_url = str(response.url)

        print(
            f"Detail response {sale.sheriff_number}: "
            f"{response.status_code} | {final_url}"
        )

        if "/Sales/SaleDetails" not in final_url:
            print(
                f"Detail redirected for "
                f"{sale.sheriff_number}; "
                "keeping listing-page data."
            )
            return sale

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        fields = self._extract_detail_fields(soup)

        if not fields:
            filename = (
                "civilview_detail_"
                f"{sale.sheriff_number.replace('-', '_')}.html"
            )

            self._save_debug_html(
                response.text,
                filename,
            )

            print(
                f"No detail fields found for "
                f"{sale.sheriff_number}. "
                f"Saved {filename}"
            )

            return sale

        return replace(
            sale,
            upset_price=self._find_money_field(
                fields,
                [
                    "upset price",
                    "upset amount",
                    "opening bid",
                ],
            ),
            judgment_amount=self._find_money_field(
                fields,
                [
                    "judgment amount",
                    "final judgment",
                    "judgment",
                ],
            ),
            plaintiff_attorney=self._find_text_field(
                fields,
                [
                    "plaintiff attorney",
                    "attorney",
                ],
            ),
            court_case_number=self._find_text_field(
                fields,
                [
                    "court case",
                    "case number",
                    "docket number",
                ],
            ),
            block=self._find_text_field(
                fields,
                ["block"],
            ),
            lot=self._find_text_field(
                fields,
                ["lot"],
            ),
            qualifier=self._find_text_field(
                fields,
                ["qualifier"],
            ),
            detail_fields=fields,
            raw_payload={
                **sale.raw_payload,
                "detail_fields": fields,
            },
        )

    def _find_sales_table(
        self,
        soup: BeautifulSoup,
    ) -> Optional[Tag]:
        """
        Find the listing table using its expected headers.
        """

        for table in soup.find_all("table"):
            headers = [
                self._normalize_header(
                    cell.get_text(" ", strip=True)
                )
                for cell in table.find_all("th")
            ]

            joined = " ".join(headers)

            if (
                "sheriff" in joined
                and "sales date" in joined
                and "address" in joined
            ):
                return table

        for table in soup.find_all("table"):
            table_text = table.get_text(
                " ",
                strip=True,
            )

            if self.SHERIFF_NUMBER_PATTERN.search(
                table_text
            ):
                return table

        return None

    def _get_header_map(
        self,
        table: Tag,
    ) -> Dict[str, int]:
        header_map: Dict[str, int] = {}

        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])

            normalized_headers = [
                self._normalize_header(
                    cell.get_text(" ", strip=True)
                )
                for cell in cells
            ]

            joined = " ".join(normalized_headers)

            if (
                "sheriff" not in joined
                or "address" not in joined
            ):
                continue

            for index, header in enumerate(
                normalized_headers
            ):
                if "sheriff" in header:
                    header_map["sheriff_number"] = index
                elif header == "status":
                    header_map["status"] = index
                elif (
                    "sales date" in header
                    or "sale date" in header
                ):
                    header_map["sale_date"] = index
                elif "plaintiff" in header:
                    header_map["plaintiff"] = index
                elif "defendant" in header:
                    header_map["defendant"] = index
                elif "address" in header:
                    header_map["address"] = index

            break

        required = {
            "sheriff_number",
            "sale_date",
            "plaintiff",
            "defendant",
            "address",
        }

        if not required.issubset(header_map):
            fallback = {
                "sheriff_number": 1,
                "sale_date": 2,
                "plaintiff": 3,
                "defendant": 4,
                "address": 5,
            }
            if "status" in joined: fallback.update(status=2,sale_date=3,plaintiff=4,defendant=5,address=6)
            return fallback

        return header_map

    def _parse_row(
        self,
        row: Tag,
        header_map: Dict[str, int],
    ) -> Optional[RawSheriffSale]:
        cells = row.find_all("td")

        if not cells:
            return None

        values = [
            cell.get_text(" ", strip=True)
            for cell in cells
        ]

        sheriff_index = self._find_sheriff_cell_index(
            values
        )

        if sheriff_index is None:
            return None

        sheriff_match = (
            self.SHERIFF_NUMBER_PATTERN.search(
                values[sheriff_index]
            )
        )

        if sheriff_match is None:
            return None

        sheriff_number = sheriff_match.group(0).upper()

        raw_status = self._column_value(
            values,
            header_map.get("status"),
        )

        sale_date_text = self._column_value(
            values,
            header_map.get("sale_date"),
        )

        plaintiff = self._column_value(
            values,
            header_map.get("plaintiff"),
        )

        defendant = self._column_value(
            values,
            header_map.get("defendant"),
        )

        address = self._column_value(
            values,
            header_map.get("address"),
        )

        if not raw_status and "status" in header_map:
            raw_status = self._column_value(
                values,
                sheriff_index + 1,
            )

        if not sale_date_text:
            sale_date_text = self._column_value(
                values,
                sheriff_index + 2,
            )

        if not plaintiff:
            plaintiff = self._column_value(
                values,
                sheriff_index + 3,
            )

        if not defendant:
            defendant = self._column_value(
                values,
                sheriff_index + 4,
            )

        if not address:
            address = self._column_value(
                values,
                sheriff_index + 5,
            )

        detail_url = self._get_detail_url(row)

        return RawSheriffSale(
            county=self.COUNTY_NAME,
            sheriff_number=sheriff_number,
            address=address,
            sale_date=self._parse_date(
                sale_date_text
            ),
            status=self._normalize_status(raw_status) if raw_status else "scheduled",
            upset_price=None,
            source_url=detail_url,
            raw_payload={
                "county_id": self.COUNTY_ID,
                "raw_status": raw_status,
                "sale_date_text": sale_date_text,
                "plaintiff": plaintiff,
                "defendant": defendant,
                "address": address,
                "all_cells": values,
            },
            plaintiff=plaintiff or None,
            defendant=defendant or None,
        )

    def _get_detail_url(
        self,
        row: Tag,
    ) -> str:
        """
        Select the SaleDetails link from the row.
        """

        for link in row.find_all("a", href=True):
            href = str(
                link.get("href", "")
            ).strip()

            if "/Sales/SaleDetails" in href:
                return urljoin(
                    self.SEARCH_URL,
                    href,
                )

        return ""

    def _extract_detail_fields(
        self,
        soup: BeautifulSoup,
    ) -> Dict[str, str]:
        """
        Extract common label/value patterns from the detail page.
        """

        fields: Dict[str, str] = {}

        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"])

            if len(cells) < 2:
                continue

            label = self._clean_label(
                cells[0].get_text(
                    " ",
                    strip=True,
                )
            )

            value = cells[1].get_text(
                " ",
                strip=True,
            )

            if label and value:
                fields[label] = value

        for term in soup.find_all("dt"):
            definition = term.find_next_sibling("dd")

            if definition is None:
                continue

            label = self._clean_label(
                term.get_text(
                    " ",
                    strip=True,
                )
            )

            value = definition.get_text(
                " ",
                strip=True,
            )

            if label and value:
                fields[label] = value

        for label_tag in soup.find_all("label"):
            label = self._clean_label(
                label_tag.get_text(
                    " ",
                    strip=True,
                )
            )

            if not label:
                continue

            control = None
            control_id = label_tag.get("for")

            if control_id:
                control = soup.find(
                    id=control_id
                )

            if control is None:
                control = label_tag.find_next(
                    [
                        "input",
                        "textarea",
                        "select",
                        "span",
                        "div",
                    ]
                )

            if control is None:
                continue

            if control.name == "input":
                value = control.get(
                    "value",
                    "",
                )
            else:
                value = control.get_text(
                    " ",
                    strip=True,
                )

            if value:
                fields[label] = str(value).strip()

        return fields

    @staticmethod
    def _browser_headers() -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        }

    @staticmethod
    def _column_value(
        values: List[str],
        index: Optional[int],
    ) -> str:
        if index is None:
            return ""

        if index < 0 or index >= len(values):
            return ""

        return values[index].strip()

    def _find_sheriff_cell_index(
        self,
        values: List[str],
    ) -> Optional[int]:
        for index, value in enumerate(values):
            if self.SHERIFF_NUMBER_PATTERN.search(
                value
            ):
                return index

        return None

    @staticmethod
    def _normalize_header(value: str) -> str:
        return " ".join(
            value.lower()
            .replace("#", " number ")
            .replace(":", " ")
            .split()
        )

    @staticmethod
    def _normalize_status(
        raw_status: str,
    ) -> str:
        value = " ".join(
            raw_status.lower()
            .strip()
            .split()
        )

        if "scheduled" in value:
            return "scheduled"

        if "bankrupt" in value:
            return "bankruptcy"

        if "adjourn" in value:
            return "adjourned"

        if "cancel" in value:
            return "cancelled"

        if "redeem" in value:
            return "redeemed"

        if "sold" in value:
            return "sold"

        if "stay" in value:
            return "stayed"

        if not value:
            return "unknown"

        return value.replace(" ", "_")

    @staticmethod
    def _parse_date(
        value: str,
    ) -> Optional[datetime]:
        cleaned = value.strip()

        formats = (
            "%m/%d/%Y",
            "%m/%d/%y",
            "%m-%d-%Y",
            "%Y-%m-%d",
            "%m/%d/%Y %I:%M:%S %p",
        )

        for date_format in formats:
            try:
                return datetime.strptime(
                    cleaned,
                    date_format,
                )
            except ValueError:
                continue

        return None

    @staticmethod
    def _clean_label(value: str) -> str:
        return " ".join(
            value.lower()
            .replace(":", " ")
            .replace("#", " number ")
            .split()
        )

    @staticmethod
    def _find_text_field(
        fields: Dict[str, str],
        possible_names: List[str],
    ) -> Optional[str]:
        for field_name, value in fields.items():
            for possible_name in possible_names:
                if possible_name in field_name:
                    return value.strip() or None

        return None

    @staticmethod
    def _find_money_field(
        fields: Dict[str, str],
        possible_names: List[str],
    ) -> Optional[Decimal]:
        for field_name, value in fields.items():
            if not any(
                possible_name in field_name
                for possible_name in possible_names
            ):
                continue

            cleaned = (
                value.replace("$", "")
                .replace(",", "")
                .strip()
            )

            match = re.search(
                r"-?\d+(?:\.\d{1,2})?",
                cleaned,
            )

            if match is None:
                continue

            try:
                return Decimal(
                    match.group(0)
                )
            except InvalidOperation:
                continue

        return None

    @staticmethod
    def _save_debug_html(
        html: str,
        filename: str,
    ) -> None:
        Path(filename).write_text(
            html,
            encoding="utf-8",
        )
