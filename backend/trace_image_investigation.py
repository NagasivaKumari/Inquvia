#!/usr/bin/env python3
"""
Runtime trace script for image investigation.
Creates a test image investigation and logs all execution steps.
"""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import db, config
from app.libraries import capabilities, engine, evidence_checks, analyzers
from app.libraries.storage import store_file
import logging

# Setup logging to capture all trace points
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger(__name__)

# Patch key functions with logging
original_image_analyzer = analyzers._image_analyzer
original_run_analysis = analyzers._run_analysis
original_read_stored_file_base64 = analyzers.read_stored_file_base64
original_execute_check = evidence_checks._execute_check
original_media_findings = evidence_checks._media_findings

async def logged_image_analyzer(inv, evidence):
    logger.info(f"=== _image_analyzer CALLED ===")
    logger.info(f"  inv['id'] = {inv.get('id')}")
    logger.info(f"  inv['question'] = {inv.get('question')}")
    logger.info(f"  len(evidence) = {len(evidence)}")
    logger.info(f"  evidence items: {[{'id': e.get('id'), 'source': e.get('source')[:50], 'signal': e.get('signal')} for e in evidence[:3]]}")
    
    images = [i for i in (inv.get("inputs") or []) if i.get("type") == "image"]
    logger.info(f"  len(images) = {len(images)}")
    for i, img in enumerate(images):
        logger.info(f"    image[{i}]: filePath={img.get('filePath')}, fileName={img.get('fileName')}, mimeType={img.get('mimeType')}")
    
    result = await original_image_analyzer(inv, evidence)
    logger.info(f"=== _image_analyzer RESULT ===")
    logger.info(f"  conclusion: {result.get('conclusion')}")
    logger.info(f"  confidence: {result.get('confidence')}")
    logger.info(f"  answer: {str(result.get('answer'))[:200]}")
    logger.info(f"  findings: {result.get('findings')}")
    logger.info(f"  limitations: {result.get('limitations')}")
    return result

async def logged_run_analysis(inv, evidence, system_prompt, context_parts, text_fallback=True):
    logger.info(f"=== _run_analysis CALLED ===")
    logger.info(f"  len(context_parts) = {len(context_parts)}")
    for i, part in enumerate(context_parts):
        if 'file' in part:
            logger.info(f"    part[{i}]: type=file, mimeType={part['file'].get('mimeType')}, base64_len={len(part['file'].get('base64', ''))}")
        elif 'text' in part:
            logger.info(f"    part[{i}]: type=text, len={len(part['text'])}, preview={part['text'][:100]}")
    
    result = await original_run_analysis(inv, evidence, system_prompt, context_parts, text_fallback)
    logger.info(f"=== _run_analysis RESULT ===")
    logger.info(f"  conclusion: {result.get('conclusion')}")
    logger.info(f"  answer: {str(result.get('answer'))[:200]}")
    return result

def logged_read_stored_file_base64(filePath):
    logger.info(f"=== read_stored_file_base64 CALLED ===")
    logger.info(f"  filePath: {filePath}")
    result = original_read_stored_file_base64(filePath)
    if result:
        logger.info(f"  RESULT: base64_length={len(result)}")
    else:
        logger.info(f"  RESULT: None (FILE NOT FOUND)")
    return result

async def logged_media_findings(inv, kind):
    logger.info(f"=== _media_findings CALLED ===")
    logger.info(f"  kind: {kind}")
    result = await original_media_findings(inv, kind)
    logger.info(f"  RESULT: {len(result)} records")
    for i, rec in enumerate(result):
        logger.info(f"    record[{i}]: finding_len={len(rec.get('finding', ''))}, finding_preview={rec.get('finding', '')[:100]}")
    return result

async def logged_execute_check(inv, cap):
    logger.info(f"=== _execute_check CALLED ===")
    logger.info(f"  capability: {cap}")
    result = await original_execute_check(inv, cap)
    logger.info(f"  RESULT: {len(result)} items")
    return result

# Apply patches
analyzers._image_analyzer = logged_image_analyzer
analyzers._run_analysis = logged_run_analysis
analyzers.read_stored_file_base64 = logged_read_stored_file_base64
evidence_checks._media_findings = logged_media_findings
evidence_checks._execute_check = logged_execute_check

async def main():
    """Create a test image investigation and trace execution."""
    db.init_db_indexes()
    
    logger.info("=" * 80)
    logger.info("STARTING IMAGE INVESTIGATION TRACE")
    logger.info("=" * 80)
    
    # Create test user
    user_id = "usr_testuser123"
    try:
        user = db.get_user_by_id(user_id)
        if not user:
            db.create_user({
                "id": user_id,
                "name": "Test User",
                "email": "test@example.com",
                "passwordHash": "hash",
                "createdAt": db.utcnow_iso(),
                "paymentPrefs": config.DEFAULT_PAYMENT_PREFS,
            })
            logger.info(f"Created test user: {user_id}")
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        return
    
    # Create test image file (small PNG)
    import tempfile
    test_image_path = Path(tempfile.gettempdir()) / "test_image_inquiry.png"
    test_image_path.write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
        b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    
    # Store the image
    with open(test_image_path, "rb") as f:
        image_data = f.read()
    
    stored_file_ref = db.store_upload_file(image_data, "test.png", "image/png", "case_test")
    logger.info(f"Stored image: {stored_file_ref}")
    
    # Create investigation inputs
    inputs = [{
        "type": "image",
        "content": "test.png",
        "fileName": "test.png",
        "mimeType": "image/png",
        "filePath": stored_file_ref,
    }]
    
    # Run image investigation
    logger.info("=" * 80)
    logger.info("CALLING run_image_investigation")
    logger.info("=" * 80)
    
    try:
        result = await capabilities.run_image_investigation({
            "id": "case_trace_test",
            "userId": user_id,
            "question": "What text and labels are visible in this image? List only information that is directly observable.",
            "inputs": inputs,
        })
        
        logger.info("=" * 80)
        logger.info("INVESTIGATION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Result ID: {result.get('id')}")
        logger.info(f"Status: {result.get('status')}")
        logger.info(f"Conclusion: {result.get('conclusion')}")
        logger.info(f"Confidence: {result.get('confidence')}")
        logger.info(f"Answer: {str(result.get('answer'))[:200]}")
        logger.info(f"Findings: {result.get('findings')}")
        logger.info(f"Limitations: {result.get('limitations')}")
        logger.info(f"Evidence count: {len(result.get('evidence', []))}")
        logger.info(f"Economic summary: {result.get('economicSummary')}")
        
        # Check payment
        payments = db.get_payments_for_investigation(result.get('id'))
        logger.info(f"Payments for investigation: {len(payments)}")
        for p in payments:
            logger.info(f"  Payment: id={p.get('id')}, investigationId={p.get('investigationId')}, amount={p.get('amount')}")
        
    except Exception as e:
        logger.error(f"Investigation failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
