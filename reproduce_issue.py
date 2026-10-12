
import re

def _correct_titmouse_pattern(text):
    """
    Titmouse 모드용: "프로젝트-쇼넘버-언더바-알파벳-씬번호" 패턴 보정
    Strict format: [MS|BM|TJS][3 digits]_[1 letter][3 digits]
    """
    if not text:
        return text

    # 1. Normalize spacing and remove invalid chars
    text = re.sub(r'\s+', '', text) # Remove all spaces
    text = text.replace(',', '').replace('.', '')
    text = text.replace('-', '_') # Hyphen to underscore
    
    # Remove other special chars but keep underscore
    text = re.sub(r'[^A-Za-z0-9_]', '', text)
    
    print(f"DEBUG: Normalized text: '{text}'")

    # 1.5 Check for Reversed Pattern: [Letter][SceneNum]_[Project][ShowNum]
    # e.g. "E003_BM802" -> "BM802_E003"
    # Relaxed regex to handle surrounding noise (removed ^ and $)
    reversed_pattern = r'([A-Z0-9])([\dOQIl]{3})_?(MS|BM|TJS)([\dOQIl]+)'
    rev_match = re.search(reversed_pattern, text, re.IGNORECASE)
    if rev_match:
        letter, scene, proj, show = rev_match.groups()
        print(f"DEBUG: Reversed match: {rev_match.groups()}")
        # Swap to correct order for further processing
        text = f"{proj}{show}_{letter}{scene}"
        print(f"DEBUG: Text after swap: '{text}'")
        # Continue to standard processing to handle normalization (O->0, etc.)

    # 2. Check for Underscore. If missing, try to insert it?
    # The user said "Underscore is mandatory".
    # But OCR might miss it.
    # If we have "BM802E003", we should probably fix it to "BM802_E003".
    
    # Let's try to match the pattern loosely first
    # Project: MS, BM, TJS (case insensitive)
    # ShowNum: 3 digits (O/Q->0, I/l->1)
    # Underscore: optional in raw, but mandatory in output
    # SceneLetter: 1 letter
    # SceneNum: 3 digits
    
    # 2. Try Refined Regex FIRST (Handles noise like "1B" before letter)
    # Checks for end of string or trailing noise handling if needed?
    # Original refined regex anchored to $
    
    pattern_refined = r'(MS|BM|TJS)([\dOQIl]+)_?([A-Z0-9]+?)([\dOQIl]{3})'
    match = re.search(pattern_refined, text, re.IGNORECASE)
    if match:
         proj, show, letter_raw, scene = match.groups()
         # print(f"DEBUG: Refined match: {match.groups()}")
         
         # Normalize Show
         show = show.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
         if len(show) > 3: 
             show = show[:3]
         else: 
             show = show.zfill(3)

         scene = scene.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
        
        # Normalize Letter
         letter_alphas = [c for c in letter_raw if c.isalpha()]
         if letter_alphas:
             letter = letter_alphas[-1].upper()
         else:
             l = letter_raw[-1]
             if l == '0': letter = 'O'
             elif l == '1': letter = 'I'
             else: letter = l.upper()
             
         return f"{proj}{show}_{letter}{scene}"

    # 3. Standard Pattern (Fallback for unanchored matches)
    # ENFORCE 3 digits for Scene Number to avoid matching prefixes like "MS101" as "MS 1 0 1"
    
    pattern = r'(MS|BM|TJS)([\dOQIl]+)_?([A-Z0-9])([\dOQIl]{3})' # Changed + to {3}
    match = re.search(pattern, text, re.IGNORECASE)
    
    if match:
        proj, show, letter, scene = match.groups()
        # print(f"DEBUG: Standard match: {match.groups()}")
        
        proj = proj.upper()
        
        show = show.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
        if len(show) != 3:
             if len(show) > 3: 
                 show = show[:3]
             else: 
                 show = show.zfill(3)
             
        letter = letter.upper()
        if letter.isdigit():
            if letter == '0': letter = 'O'
            elif letter == '1': letter = 'I'
            pass
        
        scene = scene.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
            
        return f"{proj}{show}_{letter}{scene}"
    
    # Check for Reversed Pattern LAST? Or Keep First?
    # Reversed usually has distinct structure. Keeping it early (1.5) is fine.


    return text

# Test cases
test_inputs = [
    "MS101_1BO04",
    "MS101_1BO05",
    "MS101 1 BO04",
    "MS101_1A002",
    "MS101_1BO02 - -",
    "MS101_LA015",
    "MS101_1A002",
    "MS101EBO02",
    "MS101:B002",
    "MS101_1B011",
    "MS101_1BO10"
]

print("--- Start Tests ---")
for t in test_inputs:
    res = _correct_titmouse_pattern(t)
    print(f"Input: '{t}' -> Output: '{res}'")
    print("-" * 20)
