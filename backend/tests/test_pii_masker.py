"""
tests/test_pii_masker.py
=========================
Regression tests for app/utils/pii_masker.py, grounded in this project's
real document field names (EID, Passport, Trade License, MOA, Ejari, BVI).

Run: python3 -m pytest backend/tests/test_pii_masker.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.pii_masker import mask_pii, mask_name, get_masking_stats


# ── EID ───────────────────────────────────────────────────────────────────

def test_eid_masks_name_dob_id_keeps_dates_nationality_sex():
    data = {
        "Document Type": "Emirates ID",
        "ID Number": "784-1990-1234567-1",
        "Name": "John Smith",
        "Date of Birth": "1990-05-12",
        "Nationality": "Emirati",
        "Issuing Date": "2022-01-01",
        "Expiry Date": "2032-01-01",
        "Sex": "M",
    }
    masked = mask_pii(data)

    assert masked["Name"] != "John Smith"
    assert "PERSON_" in masked["Name"]
    assert masked["Date of Birth"] == "***DOB***"
    assert masked["ID Number"].startswith("****")
    assert "784-1990-1234567-1" not in masked["ID Number"]
    assert masked["Nationality"] == "Emirati"
    assert masked["Issuing Date"] == "2022-01-01"
    assert masked["Expiry Date"] == "2032-01-01"
    assert masked["Sex"] == "M"
    assert masked["Document Type"] == "Emirates ID"


# ── Passport ──────────────────────────────────────────────────────────────

def test_passport_masks_names_dob_mrz_keeps_nationality_and_validity_dates():
    data = {
        "passport_number": "N1234567",
        "surname": "Khan",
        "given_names": "Amir",
        "nationality": "Pakistani",
        "date_of_birth": "1985-03-20",
        "sex": "M",
        "date_of_expiry": "2030-01-01",
        "date_of_issue": "2020-01-01",
        "place_of_birth": "Lahore",
        "father_name": "Imran Khan",
        "mother_name": "Sana Khan",
        "spouse_name": "Fatima Khan",
        "address": "12 Street, Dubai",
        "mrz_line1": "P<PAKKHAN<<AMIR<<<<<<<<<<<<<<<<<<<<<<<<<<<<",
        "mrz_line2": "N1234567PAK8503201M3001017<<<<<<<<<<<<<<00",
        "document_type": "Passport",
    }
    masked = mask_pii(data)

    for f in ["surname", "given_names", "father_name", "mother_name", "spouse_name"]:
        assert "PERSON_" in masked[f], f"{f} should be masked as a person"
    assert masked["date_of_birth"] == "***DOB***"
    assert masked["mrz_line1"] == "***MRZ***"
    assert masked["mrz_line2"] == "***MRZ***"
    assert masked["place_of_birth"] == "***LOCATION***"
    assert masked["address"] == "***LOCATION***"
    assert masked["nationality"] == "Pakistani"
    assert masked["sex"] == "M"
    assert masked["date_of_expiry"] == "2030-01-01"
    assert masked["date_of_issue"] == "2020-01-01"
    assert masked["document_type"] == "Passport"
    assert masked["passport_number"].startswith("****")
    assert "N1234567" not in masked["passport_number"]


# ── Trade License (Bug #2: company/trade names must survive) ────────────────

def test_trade_license_preserves_entity_names_masks_individuals():
    data = {
        "license_number": "CN-1234567",
        "company_name_english": "Acme Trading LLC",
        "company_name_arabic": "شركة أكمي",
        "trade_name_english": "Acme Trading",
        "legal_type": "LLC",
        "issue_date": "2023-01-01",
        "expiry_date": "2025-01-01",
        "owner": {
            "name_english": "Rashid Al Maktoum",
            "nationality_english": "Emirati",
            "passport_number": "P7654321",
            "date_of_birth": "1978-09-09",
            "share_percentage": 60,
            "is_direct_ubo": True,
        },
    }
    masked = mask_pii(data)

    # Entity names preserved (Bug #2 fix) — must NOT become PERSON_<hash>
    assert masked["company_name_english"] == "Acme Trading LLC"
    assert masked["trade_name_english"] == "Acme Trading"
    assert masked["license_number"] == "CN-1234567"
    assert masked["legal_type"] == "LLC"
    assert masked["issue_date"] == "2023-01-01"

    # Individual owner name IS masked
    assert "PERSON_" in masked["owner"]["name_english"]
    assert masked["owner"]["nationality_english"] == "Emirati"
    assert masked["owner"]["date_of_birth"] == "***DOB***"  # Bug #1 fix
    assert masked["owner"]["passport_number"].startswith("****")
    assert masked["owner"]["share_percentage"] == 60
    assert masked["owner"]["is_direct_ubo"] is True


# ── MOA (personal residence vs. company address) ─────────────────────────────

def test_moa_distinguishes_personal_residence_from_company_address():
    data = {
        "company_name": "Falcon Ventures LLC",
        "company_address": "Business Bay, Dubai",
        "head_office_location": "Sheikh Zayed Road, Dubai",
        "owner_name": "Layla Hassan",
        "owner_residence": "Villa 4, Jumeirah, Dubai",
        "manager_name": "Omar Faruk",
        "manager_address": "Apt 9, Marina, Dubai",
        "owner_nationality": "Emirati",
        "number_of_shares": 100,
        "share_type": "Ordinary",
    }
    masked = mask_pii(data)

    assert masked["company_name"] == "Falcon Ventures LLC"
    assert masked["company_address"] == "Business Bay, Dubai"
    assert masked["head_office_location"] == "Sheikh Zayed Road, Dubai"
    assert "PERSON_" in masked["owner_name"]
    assert "PERSON_" in masked["manager_name"]
    assert masked["owner_residence"] == "***LOCATION***"
    assert masked["manager_address"] == "***LOCATION***"
    assert masked["owner_nationality"] == "Emirati"
    assert masked["number_of_shares"] == 100


# ── Ejari (Finding #5: property identifiers preserved) ───────────────────────

def test_ejari_preserves_property_identifiers_masks_owner_contact():
    data = {
        "contract_number": "EJ-998877",
        "owner_name": "Fatima Al Suwaidi",
        "owner_number": "0501234567",
        "lessor_phone": "+971501234567",
        "lessor_email": "landlord@example.com",
        "building_name": "Marina Heights Tower",
        "plot_number": "PL-4521",
        "makani_number": "12345 67890",
        "property_number": "PN-77",
        "property_type": "Apartment",
    }
    masked = mask_pii(data)

    assert masked["contract_number"] == "EJ-998877"
    assert masked["building_name"] == "Marina Heights Tower"
    assert masked["plot_number"] == "PL-4521"
    assert masked["makani_number"] == "12345 67890"
    assert masked["property_number"] == "PN-77"
    assert masked["property_type"] == "Apartment"

    assert "PERSON_" in masked["owner_name"]
    assert masked["owner_number"].startswith("****")
    assert "0501234567" not in masked["owner_number"]
    assert "landlord" not in masked["lessor_email"]
    assert masked["lessor_email"].endswith("@example.com")


# ── BVI ───────────────────────────────────────────────────────────────────

def test_bvi_masks_people_names_keeps_entity_data():
    data = {
        "company_name": "Silverline Holdings Ltd",
        "registration_number": "BVI-445566",
        "jurisdiction": "British Virgin Islands",
        "registered_agent": "Offshore Corp Services Ltd",
        "share_capital": 50000,
        "currency": "USD",
        "people": [
            {"name": "David Chen", "role": "Director", "nationality": "Singaporean", "number_of_shares": 500},
        ],
    }
    masked = mask_pii(data)

    assert masked["company_name"] == "Silverline Holdings Ltd"
    assert masked["registered_agent"] == "Offshore Corp Services Ltd"
    assert masked["jurisdiction"] == "British Virgin Islands"
    assert masked["share_capital"] == 50000
    assert "PERSON_" in masked["people"][0]["name"]
    assert masked["people"][0]["role"] == "Director"
    assert masked["people"][0]["nationality"] == "Singaporean"
    assert masked["people"][0]["number_of_shares"] == 500


# ── Free text / bare-name-list masking ───────────────────────────────────────

def test_mask_text_patterns_uae_eid_and_phone():
    text = "Applicant EID 784-1990-1234567-1, mobile 0501234567, email a@b.com"
    masked = mask_pii(text)

    assert "784-1990-1234567-1" not in masked
    assert "0501234567" not in masked
    assert "a@b.com" not in masked
    assert "***EMAIL***" in masked
    assert "***PHONE***" in masked


def test_mask_name_bare_list_is_consistent():
    names = ["Zara Ahmed", "Zara Ahmed", "Bilal Yousef"]
    masked = [mask_name(n) for n in names]

    assert masked[0] == masked[1]          # same person -> same hash
    assert masked[0] != masked[2]
    assert all(m.startswith("PERSON_") for m in masked)
    assert "Zara" not in " ".join(masked)


# ── Stats ─────────────────────────────────────────────────────────────────

def test_masking_stats_counts_masked_and_preserved():
    original = {
        "Name": "John Doe",
        "Nationality": "British",
        "Date of Birth": "1990-01-01",
        "company_name_english": "Acme LLC",
    }
    masked = mask_pii(original)
    stats = get_masking_stats(original, masked)

    assert stats["total_fields"] == 4
    assert stats["masked_fields"] == 2   # Name, Date of Birth
    assert stats["preserved_fields"] == 2  # Nationality, company_name_english


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError:
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
