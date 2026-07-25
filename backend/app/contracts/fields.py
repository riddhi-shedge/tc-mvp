"""The §5 extraction field list — HUMAN-VERIFIED v2 (2026-07-13).

Source of truth: docs/s5-field-verification.md (approved as proposed) and the
§10 table in docs/TC-Build-Requirements.md. Do not add, rename, or reflag
fields here without a new human verification — wrong deadline-driving flags
silently corrupt every downstream timeline (§18).

Extraction is WHITELISTED to exactly these names (stronger than the Rule 2
denylist, which remains at the master as defense in depth). Contingency
removal dates are deliberately absent: removals arrive as separate CR/CR-B
documents, never extracted from the PA.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    group: str
    deadline_driving: bool
    description: str  # guides the extraction model; never assume defaults


S5_FIELDS: tuple[FieldSpec, ...] = (
    # -- Parties ---------------------------------------------------------------
    FieldSpec("buyer_names", "parties", False, "All buyer full names, comma-separated"),
    FieldSpec("seller_names", "parties", False, "All seller full names, comma-separated"),
    # -- Property --------------------------------------------------------------
    FieldSpec("property_address", "property", False, "Full property address incl. city/state/zip"),
    FieldSpec("apn", "property", False, "Assessor's Parcel Number"),
    FieldSpec(
        "items_included",
        "property",
        False,
        "Personal property/items INCLUDED in the sale (e.g. 'refrigerator, washer, dryer stay') "
        "— comma-separated; null if none listed",
    ),
    FieldSpec(
        "items_excluded",
        "property",
        False,
        "Items explicitly EXCLUDED from the sale — comma-separated; null if none listed",
    ),
    # -- Financial (amounts only — NEVER wiring/account details, Rule 2) --------
    FieldSpec("purchase_price", "financial", False, "Total purchase price in USD"),
    FieldSpec("initial_deposit_amount", "financial", False, "Initial earnest-money deposit amount"),
    FieldSpec(
        "increased_deposit_amount",
        "financial",
        False,
        "Increased deposit amount if stated (often on a separate IDA addendum — null if absent)",
    ),
    FieldSpec("loan_amount", "financial", False, "First loan amount"),
    FieldSpec(
        "financing_type", "financial", False, "Financing type (conventional/FHA/VA/seller/other)"
    ),
    FieldSpec("down_payment", "financial", False, "Down payment amount"),
    FieldSpec("all_cash", "financial", False, "true/false — is this an all-cash offer"),
    # -- Dates (deadline-driving) ------------------------------------------------
    FieldSpec(
        "acceptance_date",
        "dates",
        True,
        "Acceptance date (Confirmation of Acceptance box if completed — it is optional, "
        "so report LOW confidence when inferred; the operative date is personal receipt)",
    ),
    FieldSpec(
        "close_of_escrow",
        "dates",
        True,
        "Close of escrow: a specific date OR a number of days after acceptance — report exactly as written",
    ),
    FieldSpec("possession_date", "dates", True, "Possession date/time terms"),
    # -- Contingency periods (deadline-driving; report the number written on the form) --
    FieldSpec(
        "emd_due_days", "contingency", True, "Days after acceptance the initial deposit is due"
    ),
    FieldSpec(
        "inspection_contingency_days",
        "contingency",
        True,
        "Investigation/inspection contingency days, or 'waived'",
    ),
    FieldSpec("loan_contingency_days", "contingency", True, "Loan contingency days, or 'waived'"),
    FieldSpec(
        "appraisal_contingency_days", "contingency", True, "Appraisal contingency days, or 'waived'"
    ),
    FieldSpec(
        "insurance_contingency_days",
        "contingency",
        True,
        "Insurance contingency days (standalone since Jun 2024), or 'waived'",
    ),
    FieldSpec(
        "disclosure_delivery_days",
        "contingency",
        True,
        "Days for seller disclosure/document delivery",
    ),
    FieldSpec(
        "verification_of_funds_days",
        "contingency",
        True,
        "Days for buyer's verification of down payment and closing costs",
    ),
    # -- Flags -------------------------------------------------------------------
    FieldSpec("loan_contingency_present", "flags", False, "true/false — loan contingency applies"),
    FieldSpec(
        "appraisal_contingency_present",
        "flags",
        False,
        "true/false — appraisal contingency applies",
    ),
    FieldSpec(
        "inspection_contingency_present",
        "flags",
        False,
        "true/false — inspection contingency applies",
    ),
    FieldSpec(
        "insurance_contingency_present",
        "flags",
        False,
        "true/false — insurance contingency applies",
    ),
    # -- Cost allocation (WHO pays — allocation ONLY, never a dollar amount; Rule 2) --
    FieldSpec(
        "home_warranty_paid_by",
        "allocation",
        False,
        "Who pays for the home-warranty plan: 'buyer' / 'seller' / 'split' / 'none' — "
        "who-pays only, NEVER an amount (Rule 2)",
    ),
    FieldSpec(
        "home_warranty_issued_by",
        "allocation",
        False,
        "Home-warranty company/plan named on the form, or \"buyer's choice\" if the buyer "
        "selects the provider; null if blank",
    ),
    # -- Other terms -------------------------------------------------------------
    FieldSpec(
        "other_terms",
        "terms",
        False,
        "Other/additional terms or special clauses written on the agreement (short freeform "
        "summary of what is written — never invented); null if none",
    ),
    # -- Contacts (no wiring data ever; lender/title often absent from the form) --
    FieldSpec("buyer_agent", "contacts", False, "Buyer's agent and brokerage"),
    FieldSpec("listing_agent", "contacts", False, "Listing agent and brokerage"),
    FieldSpec(
        "escrow_holder",
        "contacts",
        False,
        "Escrow holder/company from the Escrow Holder Acknowledgment",
    ),
    FieldSpec(
        "title_company",
        "contacts",
        False,
        "Title company if stated (no dedicated block — often absent)",
    ),
    FieldSpec(
        "lender_contact",
        "contacts",
        False,
        "Lender/loan officer if written in (usually NOT on the form)",
    ),
)

EXTRACTABLE_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in S5_FIELDS)

DEADLINE_DRIVING: frozenset[str] = frozenset(f.name for f in S5_FIELDS if f.deadline_driving)


def is_extractable_field(name: str) -> bool:
    return name in EXTRACTABLE_FIELD_NAMES


def is_deadline_driving(name: str) -> bool:
    return name in DEADLINE_DRIVING
