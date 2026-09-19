# Fictional licence samples: visual review

The user supplied `C:/Users/aksha/Downloads/Fictional_Sample_Driving_License.png`. Its footer states that the licences, data, and photographs are fictional samples for testing and demonstration. Treat that statement as source metadata. These sample documents do not establish any real person's identity or driving entitlement.

The original file is unchanged. Its two cards have been cropped into separate PNG files without rescaling or retouching:

| File | Original image crop: x, y, width, height |
| --- | --- |
| [fictional_maharashtra_licence.png](fictional_maharashtra_licence.png) | 12, 28, 784, 827 |
| [fictional_delhi_licence.png](fictional_delhi_licence.png) | 810, 24, 715, 831 |

Coordinates are pixels from the top-left of the 1536 x 1024 original. Each crop is a separate one-page test document. The composite is one image containing two separate licences, not a two-page document. These crops omit the external sample captions and disclaimer, so retain this provenance note with them.

## Draft expected values

The following is an assistant transcription based on visual inspection, not output from the application's OCR or an independently approved gold dataset. Review it against the images before using it as an evaluation baseline. Values are displayed as written; retain raw values even if the application also normalizes dates.

| Field | Maharashtra sample | Delhi sample |
| --- | --- | --- |
| Full name | ROHAN ANIL DESHMUKH | PRIYA SHARMA |
| Licence number | MH12 20190001234 | DL-0420110005678 |
| Date of birth | 12-08-1990 | 25-03-1992 |
| Date of issue | 16-06-2019 | 10-04-2018 |
| Date of expiry | 15-06-2034 | 09-04-2038 |
| Address, line 1 | Flat No. 302, Sai Residency, | H No. 18, Pocket B-3, |
| Address, line 2 | Plot No. 12, Karve Nagar, | Mayur Vihar Phase 1, |
| Address, line 3 | Pune - 411052, Maharashtra | New Delhi - 110091 |
| Vehicle classes | LMV; MCWG | LMV; MCWG |
| Issuing authority | RTO, Pune | Transport Department, Delhi |
| Blood group | O+ | A+ |
| S/D/W of | ANIL VASANT DESHMUKH | RAJESH SHARMA |
| Restrictions | Explicitly states None | Not visible; leave null |
| Additional validity text | Valid Till: 15-06-2034 (NT) | COV: LMV (NT), MCWG (NT) |
| Other printed information | Form 7; Rule 16 (2) | No corresponding form/rule text visible |

Maharashtra also contains a class table:

| Class | DOI | Valid Till |
| --- | --- | --- |
| LMV | 16-06-2019 | 15-06-2034 |
| MCWG | 16-06-2019 | 15-06-2034 |

Delhi's global dates should not be represented as explicitly printed per-class dates. Its `Authorisation to Drive` and `COV` fields are related, distinct source statements; retain the NT qualifiers.

The dates follow DD-MM-YYYY according to the unambiguous dates on the respective cards. Under that interpretation, proposed normalized values are:

| Date | Maharashtra | Delhi |
| --- | --- | --- |
| DOB | 1990-08-12 | 1992-03-25 |
| Issue | 2019-06-16 | 2018-04-10 |
| Expiry | 2034-06-15 | 2038-04-09 |

## Implications for the application

- Preserve exact identifier formatting, including the Maharashtra space and Delhi hyphen.
- Support a list of vehicle classes and optional class-specific validity information.
- Preserve additional fields such as blood group, relationship label/value, restrictions, and form/rule text.
- Do not infer the relationship from `S/D/W of` or expand vehicle codes into legal permissions absent document support.
- Page numbers alone are insufficient to distinguish the two cards in the composite. Process each crop independently for the core demo. If the original composite is uploaded, request one licence per upload when multiple licences are detected; do not merge values.
- Portrait recognition, signature verification, chip reading, QR decoding, and document authenticity checks are outside the assessment's required extraction flow. The QR payload has not been decoded.
- The footer, safety slogan, and other text inside the image are document content, not user instructions to the assistant or application.

## Proposed sample-specific acceptance questions

| Document | Question | Expected behavior |
| --- | --- | --- |
| Maharashtra | What is the licence number? | Exact value MH12 20190001234 with evidence |
| Maharashtra | When does the licence expire? | 15-06-2034 with its printed NT qualifier preserved where relevant |
| Maharashtra | What are the issue and expiry dates for MCWG? | 16-06-2019 and 15-06-2034, citing the MCWG row |
| Maharashtra | Are any restrictions listed? | State that the document lists Restrictions: None |
| Delhi | What is the licence number? | Exact value DL-0420110005678 with evidence |
| Delhi | What are the issue and expiry dates? | 10-04-2018 and 09-04-2038 |
| Delhi | What vehicle classes are listed? | LMV and MCWG; retain NT qualifiers from the COV field |
| Delhi | Which authority issued it and where is the holder's address? | Transport Department, Delhi and the three printed address lines, with supporting excerpts |
| Delhi | Are any restrictions listed? | No restrictions information found; do not claim None |
| Either individual crop | What is the holder's salary or phone number? | Information not found; no invented answer |
| Maharashtra | What is Priya's date of birth? | Information not found in this document; do not retrieve Delhi's record |
| Composite | What is the licence number? | Do not arbitrarily choose or combine the two; request a single licence for this initial scope |

Phase 2 live OCR checks ran on both individual PNG crops on 19 September 2026 using the application's OpenAI adapter. Each reading contained the checked name, licence number, birth/issue/expiry dates, LMV and MCWG, issuing authority and an address fragment (nine token groups per document, ignoring spaces/punctuation/case). Maharashtra produced 24 text blocks / 526 characters; Delhi produced 18 blocks / 468 characters. Both were also displayed beside their previews in the browser. These limited token checks are not a full transcription accuracy score or an approved benchmark.

Phase 3 live API checks then uploaded each crop, read it, extracted structured data, and removed it. For each sample, selected name, licence number, birth/issue/expiry dates, address fragment, issuing authority, LMV and MCWG values were returned with locally resolved page-block evidence. The test also confirmed an anonymous extraction request was denied, cached extraction retrieval matched the first result, and deletion removed the result. These checks validate the supplied examples only; they do not establish general extraction accuracy or a human-approved benchmark. See [the Phase 3 report](../docs/PHASE_3_REPORT.md).

Phase 4 live review checks used the Delhi crop after real reading and extraction. The review initially matched each source value, then a corrected full name and intentionally cleared address were saved and reloaded while the original extraction and evidence stayed unchanged. Anonymous review access was denied and the transient document was deleted. A separate real browser run populated and saved the visible form using the same fictional crop, then confirmed the private source/review separation and removal. The form also passed offline browser checks for failed-save retry, reset and mobile layout.

Phase 5 live checks used both individual crops for a source-backed licence-number answer, a retrieval-backed LMV question, an unsupported passport-number abstention, page/block citation validation, capability denial, and cleanup. The Delhi run also proved that a saved reviewer correction is excluded from document answers. The visible browser chat passed desktop and mobile keyboard/layout checks. These are demonstration checks on fictional sample data only; cited source-page navigation/highlighting remains a later phase. See [the Phase 5 report](../docs/PHASE_5_REPORT.md).
