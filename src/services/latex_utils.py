"""
LaTeX Utils Service

Convert LaTeX formulas to Unicode or render them as images.
Can be used with any LLM output (Gemini, GLM, etc.)
"""

import logging
import os
import re
import hashlib

logger = logging.getLogger(__name__)


# LaTeX command to Unicode mapping
LATEX_TO_UNICODE = {
    # Greek letters
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η', r'\theta': 'θ',
    r'\iota': 'ι', r'\kappa': 'κ', r'\lambda': 'λ', r'\mu': 'μ',
    r'\nu': 'ν', r'\xi': 'ξ', r'\pi': 'π', r'\rho': 'ρ',
    r'\sigma': 'σ', r'\tau': 'τ', r'\upsilon': 'υ', r'\phi': 'φ',
    r'\chi': 'χ', r'\psi': 'ψ', r'\omega': 'ω',
    r'\Gamma': 'Γ', r'\Delta': 'Δ', r'\Theta': 'Θ', r'\Lambda': 'Λ',
    r'\Xi': 'Ξ', r'\Pi': 'Π', r'\Sigma': 'Σ', r'\Phi': 'Φ',
    r'\Psi': 'Ψ', r'\Omega': 'Ω',
    
    # Operators
    r'\sum': '∑', r'\prod': '∏', r'\int': '∫',
    r'\partial': '∂', r'\nabla': '∇', r'\infty': '∞',
    r'\approx': '≈', r'\neq': '≠', r'\leq': '≤', r'\geq': '≥',
    r'\le': '≤', r'\ge': '≥', r'\ll': '≪', r'\gg': '≫',
    r'\pm': '±', r'\mp': '∓', r'\times': '×', r'\div': '÷',
    r'\cdot': '·', r'\circ': '∘', r'\bullet': '•',
    r'\in': '∈', r'\notin': '∉', r'\subset': '⊂', r'\supset': '⊃',
    r'\cup': '∪', r'\cap': '∩', r'\emptyset': '∅',
    r'\forall': '∀', r'\exists': '∃', r'\neg': '¬',
    r'\land': '∧', r'\lor': '∨', r'\oplus': '⊕',
    r'\rightarrow': '→', r'\leftarrow': '←', r'\Rightarrow': '⇒',
    r'\Leftarrow': '⇐', r'\leftrightarrow': '↔', r'\Leftrightarrow': '⇔',
    r'\to': '→', r'\mapsto': '↦',
    
    # Other symbols
    r'\sqrt': '√', r'\degree': '°', r'\prime': '′',
    r'\ldots': '…', r'\cdots': '⋯', r'\vdots': '⋮',
    r'\therefore': '∴', r'\because': '∵',
    r'\propto': '∝', r'\equiv': '≡', r'\sim': '∼',
    r'\cong': '≅', r'\perp': '⊥', r'\parallel': '∥',
    r'\angle': '∠', r'\triangle': '△',
    
    # Spaces and formatting
    r'\quad': ' ', r'\qquad': '  ', r'\,': '', r'\;': ' ', r'\!': '',
    r'\\': '\n', r'\newline': '\n',
}

SUPERSCRIPT_MAP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '-': '⁻', 'n': 'ⁿ', 'i': 'ⁱ', 'T': 'ᵀ'
}

SUBSCRIPT_MAP = {
    # Numbers
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    # Operators
    '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
    # All available Unicode subscript letters (no b,c,d,f,g,q,w,y,z exist)
    'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ', 'j': 'ⱼ',
    'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ',
    'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ',
    'v': 'ᵥ', 'x': 'ₓ',
}


def _convert_single_formula(formula: str) -> str:
    """Convert a single LaTeX formula to Unicode"""
    result = formula
    
    # Replace LaTeX commands with Unicode
    for latex, unicode_char in LATEX_TO_UNICODE.items():
        result = result.replace(latex, unicode_char)
    
    # Handle \frac{a}{b} -> a/b (add parens only if content has operators)
    def frac_replace(m):
        num, denom = m.group(1), m.group(2)
        # Only wrap in parens if content has spaces/operators
        num_wrap = f"({num})" if len(num) > 1 and any(c in num for c in ' +-*/') else num
        denom_wrap = f"({denom})" if len(denom) > 1 and any(c in denom for c in ' +-*/') else denom
        return f"{num_wrap}/{denom_wrap}"
    result = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', frac_replace, result)
    
    # Handle \sqrt{x} -> √x (add parens only if content has multiple chars with operators)
    def sqrt_replace(m):
        content = m.group(1)
        if len(content) > 1 and any(c in content for c in ' +-*/'):
            return f"√({content})"
        return f"√{content}"
    result = re.sub(r'√\{([^}]*)\}', sqrt_replace, result)
    
    # Handle \text{...} -> just the text
    result = re.sub(r'\\text\{([^}]*)\}', r'\1', result)
    result = re.sub(r'\\textbf\{([^}]*)\}', r'\1', result)
    result = re.sub(r'\\textit\{([^}]*)\}', r'\1', result)
    result = re.sub(r'\\mathrm\{([^}]*)\}', r'\1', result)
    result = re.sub(r'\\mathbf\{([^}]*)\}', r'\1', result)
    
    # Handle superscripts ^{...} -> unicode superscript
    def sup_replace(m):
        content = m.group(1)
        return ''.join(SUPERSCRIPT_MAP.get(c, f'^{c}') for c in content)
    result = re.sub(r'\^\{([^}]*)\}', sup_replace, result)
    result = re.sub(r'\^([0-9TnN])', lambda m: SUPERSCRIPT_MAP.get(m.group(1), f'^{m.group(1)}'), result)
    
    # Handle subscripts _{...} -> unicode subscript
    def sub_replace(m):
        content = m.group(1)
        return ''.join(SUBSCRIPT_MAP.get(c, f'_{c}') for c in content)
    result = re.sub(r'_\{([^}]*)\}', sub_replace, result)
    # Match single-char subscripts (numbers and all lowercase letters)
    result = re.sub(r'_([0-9a-z])', lambda m: SUBSCRIPT_MAP.get(m.group(1), f'_{m.group(1)}'), result)
    
    # Clean up remaining braces
    result = result.replace('{', '').replace('}', '')
    
    # Clean up backslashes from unknown commands
    result = re.sub(r'\\([a-zA-Z]+)', r'\1', result)
    
    return result.strip()


def convert_latex_to_unicode(text: str) -> str:
    """
    Convert inline LaTeX formulas ($...$) to Unicode symbols.
    Block formulas ($$...$$) are left unchanged for image rendering.
    
    Args:
        text: Text containing LaTeX formulas
        
    Returns:
        Text with inline formulas converted to Unicode
        
    Example:
        "$\\alpha + \\beta$" -> "α + β"
        "$x^2 + y_1$" -> "x² + y₁"
    """
    # Only convert inline $...$ formulas (not $$...$$)
    return re.sub(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', 
                  lambda m: _convert_single_formula(m.group(1)), text)


def render_latex_to_image(latex: str, output_path: str) -> bool:
    """
    Render LaTeX formula to an image file using matplotlib.
    
    Args:
        latex: LaTeX formula string (without $$ delimiters)
        output_path: Path to save the output image
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
        
        # Create figure with Discord dark theme background
        fig, ax = plt.subplots(figsize=(12, 1.5), dpi=150)
        ax.set_facecolor('#36393f')  # Discord dark theme
        fig.patch.set_facecolor('#36393f')
        
        # Render LaTeX
        ax.text(0.5, 0.5, f"${latex}$", 
                fontsize=18, 
                ha='center', va='center',
                color='white',
                transform=ax.transAxes)
        ax.axis('off')
        
        # Save with tight bounding box
        fig.savefig(output_path, 
                    format='png', 
                    bbox_inches='tight', 
                    pad_inches=0.1,
                    facecolor='#36393f',
                    edgecolor='none')
        plt.close(fig)
        
        logger.info(f"Rendered LaTeX to image: {output_path}")
        return True
        
    except Exception as e:
        logger.warning(f"Failed to render LaTeX to image: {e}")
        return False


def process_latex_formulas(text: str, output_dir: str = "/tmp") -> tuple[str, list[tuple[str, str]]]:
    """
    Process LaTeX formulas in text:
    - $$...$$ (block formulas): Render to image, replace with placeholder
    - $...$ (inline formulas): Convert to Unicode symbols
    
    This is the main function to call before sending any LLM output to Discord.
    
    Args:
        text: Text containing LaTeX formulas
        output_dir: Directory to save rendered images
        
    Returns:
        Tuple of (processed_text, list of (placeholder, image_path))
        
    Example:
        text = "The formula is: $$\\frac{a}{b}$$ and $\\alpha$"
        processed, images = process_latex_formulas(text)
        # processed = "The formula is: [-LATEX_IMG:xxx-] and α"
        # images = [("[-LATEX_IMG:xxx-]", "/tmp/latex_xxx.png")]
    """
    images = []
    
    # First, handle block formulas $$...$$
    def process_block_formula(match):
        latex = match.group(1).strip()
        
        # Generate unique filename based on formula hash
        formula_hash = hashlib.md5(latex.encode()).hexdigest()[:8]
        image_path = os.path.join(output_dir, f"latex_{formula_hash}.png")
        
        # Try to render to image
        if render_latex_to_image(latex, image_path):
            placeholder = f"[-LATEX_IMG:{formula_hash}-]"
            images.append((placeholder, image_path))
            return f"\n{placeholder}\n"
        else:
            # Fallback to Unicode conversion if image rendering fails
            return _convert_single_formula(latex)
    
    # Process block formulas ($$...$$)
    text = re.sub(r'\$\$(.+?)\$\$', process_block_formula, text, flags=re.DOTALL)
    
    # Then convert inline formulas to Unicode
    text = convert_latex_to_unicode(text)
    
    return text, images


def cleanup_latex_images(images: list[tuple[str, str]]) -> None:
    """
    Clean up rendered LaTeX images.
    
    Args:
        images: List of (placeholder, image_path) tuples from process_latex_formulas
    """
    for _, img_path in images:
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
        except Exception as e:
            logger.warning(f"Failed to delete LaTeX image {img_path}: {e}")
