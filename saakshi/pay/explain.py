"""Plain-language payslip explanations in en, ta, hi and or."""
from __future__ import annotations

HELD = {
    "en": "Your payslip is on hold: a record of your hours was changed after it was signed. "
          "Your receipts prove what really happened.",
    "ta": "உங்கள் ஊதியச் சீட்டு நிறுத்தப்பட்டுள்ளது: கையொப்பமிட்ட பின் உங்கள் நேரப் பதிவு மாற்றப்பட்டது. "
          "உங்கள் ரசீதுகள் உண்மையை நிரூபிக்கும்.",
    "hi": "आपकी वेतन पर्ची रोकी गई है: हस्ताक्षर के बाद आपके घंटों का रिकॉर्ड बदला गया। आपकी रसीदें सच साबित करती हैं।",
    "or": "ଆପଣଙ୍କ ଦରମା ପତ୍ର ରୋକାଯାଇଛି: ସ୍ୱାକ୍ଷର ପରେ ଆପଣଙ୍କ ସମୟ ରେକର୍ଡ ବଦଳାଯାଇଛି।",
}
"""Shown instead of the figures when a payslip is held."""


def explanation(days: int, ot_hours: float, ot_rate: float, net: float, held: bool) -> dict[str, str]:
    """Explain a payslip in each language: days, overtime hours and hourly overtime rate, and net pay (or why it is held)."""
    if held:
        return dict(HELD)
    return {
        "en": f"You worked {days} days and {ot_hours:g} overtime hours. Overtime is paid at double rate: ₹{ot_rate} an hour. "
              f"After PF and ESI, you get ₹{net:,.2f}.",
        "ta": f"நீங்கள் {days} நாட்கள் மற்றும் {ot_hours:g} கூடுதல் மணி நேரம் வேலை செய்தீர்கள். கூடுதல் நேரத்திற்கு இரட்டை ஊதியம்: "
              f"மணிக்கு ₹{ot_rate}. PF, ESI பிடித்தம் போக, உங்களுக்கு ₹{net:,.2f}.",
        "hi": f"आपने {days} दिन और {ot_hours:g} घंटे ओवरटाइम काम किया। ओवरटाइम दोगुनी दर पर: ₹{ot_rate} प्रति घंटा। "
              f"PF और ESI के बाद आपको ₹{net:,.2f} मिलेंगे।",
        "or": f"ଆପଣ {days} ଦିନ ଏବଂ {ot_hours:g} ଘଣ୍ଟା ଅତିରିକ୍ତ କାମ କଲେ। ଅତିରିକ୍ତ ସମୟ ଦୁଇଗୁଣ ହାରରେ: ଘଣ୍ଟା ପିଛା ₹{ot_rate}। "
              f"PF ଓ ESI ପରେ ଆପଣ ₹{net:,.2f} ପାଇବେ।",
    }
