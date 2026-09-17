"""Conservative property scope for the NY/IL residential AVM candidates."""

NY_SALESWEB = "ny_orpts_salesweb_rp5217"
NY_ASSESSMENT = "ny_orpts_local_assessment_rolls_2021_2025"
IL_COOK = "il_cook_assessor_1999_present"
IL_MYDEC = "il_idor_mydec_2014_present"


def residential_scope(state: str, source_id: str | None, land_use_code: str | None) -> bool:
    code = str(land_use_code or "").strip().upper()
    if state == "NY":
        return source_id in {NY_SALESWEB, NY_ASSESSMENT} and code.isdigit() and 210 <= int(code) <= 299
    if state == "IL":
        if source_id == IL_MYDEC:
            return code == "B"
        return source_id == IL_COOK and code.isdigit() and 201 <= int(code) <= 299
    return False
