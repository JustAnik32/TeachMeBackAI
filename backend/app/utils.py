import os
import uuid
import base64
from fpdf import FPDF
from PIL import Image
import io


def ensure_dir(p):
    if not os.path.exists(p):
        os.makedirs(p, exist_ok=True)


def triage_case(data: dict):
    matched = []
    temp = data.get('temperature')
    try:
        if temp is not None:
            temp = float(temp)
    except Exception:
        temp = None
    if temp is not None and temp >= 38.0:
        matched.append('High fever (>=38°C)')
    if data.get('shortness_of_breath'):
        matched.append('Shortness of breath')
    oxy = data.get('oxygen_saturation')
    try:
        if oxy is not None:
            oxy = int(oxy)
    except Exception:
        oxy = None
    if oxy is not None and oxy < 94:
        matched.append('Low oxygen saturation (<94%)')

    # severity rules (conservative)
    if 'Shortness of breath' in matched or (oxy is not None and oxy < 90) or (temp is not None and temp >= 40):
        severity = 'red'
    elif len(matched) >= 1:
        severity = 'yellow'
    else:
        severity = 'green'

    return {'severity': severity, 'matched_rules': matched}


def save_image_from_base64(b64_str: str, out_dir: str, prefix: str = 'img'):
    ensure_dir(out_dir)
    # Accept both raw base64 and data URI
    header, sep, data = b64_str.partition(',')
    if sep:
        data = data
    else:
        data = header
    try:
        imgdata = base64.b64decode(data)
        filename = f"{prefix}_{uuid.uuid4().hex}.png"
        path = os.path.join(out_dir, filename)
        with open(path, 'wb') as f:
            f.write(imgdata)
        # verify and possibly convert
        try:
            im = Image.open(path)
            im = im.convert('RGB')
            im.save(path)
        except Exception:
            pass
        return path
    except Exception:
        return None


def generate_evidence_pdf(case: dict, out_dir: str):
    ensure_dir(out_dir)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "MicroClinic Evidence Pack", ln=True)
    pdf.ln(4)
    pdf.cell(0, 8, f"ID: {case.get('id')}", ln=True)
    pdf.cell(0, 8, f"Patient: {case.get('patient_name')}", ln=True)
    pdf.cell(0, 8, f"Age: {case.get('age')}", ln=True)
    pdf.cell(0, 8, f"Created at: {case.get('created_at')}", ln=True)
    pdf.ln(4)
    pdf.cell(0, 8, "Symptoms:", ln=True)
    for s in case.get('symptoms', []):
        pdf.cell(0, 6, f"- {s}", ln=True)
    if case.get('temperature') is not None:
        pdf.cell(0, 6, f"Temperature: {case.get('temperature')} C", ln=True)
    if case.get('oxygen_saturation') is not None:
        pdf.cell(0, 6, f"Oxygen saturation: {case.get('oxygen_saturation')}", ln=True)
    pdf.ln(2)
    pdf.cell(0, 8, f"Severity: {case.get('severity')}", ln=True)
    pdf.cell(0, 8, "Matched rules:", ln=True)
    for r in case.get('matched_rules', []):
        pdf.cell(0, 6, f"- {r}", ln=True)
    pdf.ln(4)
    if case.get('notes'):
        pdf.multi_cell(0, 6, f"Notes: {case.get('notes')}")
    pdf.ln(2)
    if case.get('submitted_by_name'):
        pdf.cell(0, 6, f"Submitted by: {case.get('submitted_by_name')}", ln=True)
    if case.get('signature'):
        pdf.ln(2)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 6, f"Signature: {case.get('signature')}", ln=True)
        pdf.set_font("Arial", size=12)

    # Add image if present
    img_path = case.get('image_path')
    if img_path and os.path.exists(img_path):
        try:
            pdf.add_page()
            pdf.image(img_path, x=10, y=20, w=180)
        except Exception:
            pass

    out_path = os.path.join(out_dir, f"evidence_{case.get('id')}.pdf")
    pdf.output(out_path)
    return out_path
