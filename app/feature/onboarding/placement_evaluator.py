"""
Placement test evaluation logic — pure backend, no AI.
Implements v2.1 spec §3: global average + Spiky-Profile Cap.
"""

def classify_user(skill_scores: dict[str, float]) -> tuple[str, list[str]]:
    """
    Classify user level from placement test results.
    
    Args:
        skill_scores: Dict mapping skill tag (D_doc, C_comm, T_trouble, G_custom) 
                     to fraction correct (0.0–1.0).
    
    Returns:
        Tuple of (starting_level, weak_skills) where:
        - starting_level: 'basic' | 'intermediate' | 'advanced'
        - weak_skills: list of skill tags where score < 0.5, ordered weakest first
    """
    # Default to 0.0 for any missing skill (robustness)
    scores = {
        "D_doc": skill_scores.get("D_doc", 0.0),
        "C_comm": skill_scores.get("C_comm", 0.0),
        "T_trouble": skill_scores.get("T_trouble", 0.0),
        "G_custom": skill_scores.get("G_custom", 0.0),
    }
    
    # Global average
    overall = sum(scores.values()) / len(scores)
    
    # Spiky-Profile Cap: never let a strong overall hide a weak skill
    min_skill = min(scores.values())
    
    # Determine starting level (spec §3)
    if overall >= 0.75 and min_skill >= 0.50:
        starting_level = "advanced"
    elif overall >= 0.75 and min_skill < 0.50:
        starting_level = "intermediate"  # capped
    elif 0.45 <= overall < 0.75 and min_skill >= 0.30:
        starting_level = "intermediate"
    else:
        starting_level = "basic"  # overall < 0.45 OR any skill < 0.30
    
    # Weak skills: all skills < 0.5, ordered weakest first
    weak_skills = [
        skill for skill, score in sorted(scores.items(), key=lambda x: x[1])
        if score < 0.5
    ]
    
    return starting_level, weak_skills