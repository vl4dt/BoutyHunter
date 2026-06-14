# BoutyHunter - Bug Bounty Program Scoring

## Overview

BoutyHunter is a tool that analyzes bug bounty programs and scores them based on multiple factors including:
- Competition level
- Triage speed 
- Focus area bonuses (with LLM-based validation)
- Payout amounts

## Key Features

### 1. LLM-Based Scope Analysis
The system uses an LLM to determine whether programs actually award bounties for vulnerabilities in each focus area, rather than relying on brittle substring matching that could produce false positives.

### 2. Smart Scoring Logic
- **Focus Area Bonuses**: Programs get full bonuses when they actually offer bounties for vulnerabilities in their stated focus areas
- **Reduced Bonuses**: Programs that mention a focus area but don't actually pay for it receive reduced bonuses (0.4x reduction)
- **Competition Penalty**: Lower competition = higher scores

### 3. Example Behavior
**Kruidvat Program**:
- Has `focus_areas: ['llm']` 
- No actual AI content in description or scope
- Scored with reduced bonus: `Focus: LLM/AI — emerging field, least competition (no bounties in-scope) → +3.2`

**AI Security Test Program**:  
- Has `focus_areas: ['llm']`
- Actual AI content in description and scope
- Scored with full bonus: `Focus: LLM/AI — emerging field, least competition → +8`

## Configuration

### Environment Variables

```bash
export LLM_BASE_URL="http://10.74.74.151:1234/v1"  # LM Studio endpoint
export LLM_MODEL="qwen/qwen3-coder-30b"            # Model to use
```

## Usage

```python
from scoring import score_program

# Score a single program
program = {
    "name": "Example Program",
    "url": "https://hackerone.com/example",
    "platform": "hackerone",
    "description": "Company with AI security focus",
    "focus_areas": ["llm"],
    "scope_details": {
        "scope": [{"type": "url", "value": "https://api.example.com/*"}],
        "exclusions": []
    },
    "max_payout_usd": 10000
}

score, reasons = score_program(program)
print(f"Score: {score}")
for reason in reasons:
    print(f"  - {reason}")
```

## Implementation Details

### Core Logic

The scoring system now properly distinguishes between programs that:
1. **Mention a focus area but don't actually pay for it** → Gets reduced bonus (0.4x)
2. **Mention a focus area AND actually pay for it** → Gets full bonus

This addresses the original requirement: "Verify that when evaluating the programs the ones who have scopes in my interests also must be awarding bounties in the scope of interest otherwise it should score less than the ones that do."

### LLM Integration

The system:
- Uses your local LM Studio at `http://10.74.74.151:1234/v1` with `qwen/qwen3-coder-30b` model
- Analyzes program description and scope details to determine actual bounty coverage
- Falls back gracefully to keyword checking when LLM is unavailable

## Files

- `scoring.py`: Core scoring logic with LLM integration
- `program_browser.py`: CLI interface with progress indicators  
- `tui_app.py`: TUI application (requires rich library)

## Requirements

- Python 3.7+
- LM Studio server running at `http://10.74.74.151:1234/v1`
- Model `qwen/qwen3-coder-30b` loaded in LM Studio