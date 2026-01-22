#!/bin/bash

# Claude Code Project Setup Script
# Usage: ./setup-project.sh [project-path]
# Or:    ./setup-project.sh (uses current directory)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory (where templates are)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/project"

# Target directory
TARGET_DIR="${1:-.}"
TARGET_DIR="$(cd "$TARGET_DIR" 2>/dev/null && pwd || echo "$TARGET_DIR")"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Claude Code Project Setup${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if template directory exists
if [ ! -d "$TEMPLATE_DIR" ]; then
    echo -e "${RED}Error: Template directory not found at $TEMPLATE_DIR${NC}"
    exit 1
fi

# Create target directory if it doesn't exist
if [ ! -d "$TARGET_DIR" ]; then
    echo -e "${YELLOW}Creating directory: $TARGET_DIR${NC}"
    mkdir -p "$TARGET_DIR"
fi

echo -e "${GREEN}Target:${NC} $TARGET_DIR"
echo ""

# Function to copy file with status
copy_file() {
    local src="$1"
    local dest="$2"
    local name="$3"

    if [ -f "$dest" ]; then
        echo -e "  ${YELLOW}[skip]${NC} $name (already exists)"
        return 0
    fi

    if [ -f "$src" ]; then
        cp "$src" "$dest"
        echo -e "  ${GREEN}[done]${NC} $name"
    else
        echo -e "  ${RED}[miss]${NC} $name (template not found)"
    fi
}

# Copy root files
echo -e "${BLUE}Copying project files...${NC}"
copy_file "$TEMPLATE_DIR/CLAUDE.md" "$TARGET_DIR/CLAUDE.md" "CLAUDE.md"
copy_file "$TEMPLATE_DIR/INFRASTRUCTURE.md" "$TARGET_DIR/INFRASTRUCTURE.md" "INFRASTRUCTURE.md"
copy_file "$TEMPLATE_DIR/_FRAGILE.md" "$TARGET_DIR/_FRAGILE.md" "_FRAGILE.md"
copy_file "$TEMPLATE_DIR/_NEXT_SESSION_MEMO.md" "$TARGET_DIR/_NEXT_SESSION_MEMO.md" "_NEXT_SESSION_MEMO.md"
copy_file "$TEMPLATE_DIR/_VOCABULARY.md" "$TARGET_DIR/_VOCABULARY.md" "_VOCABULARY.md"

# Create .claude directory structure
echo ""
echo -e "${BLUE}Setting up .claude folder...${NC}"
mkdir -p "$TARGET_DIR/.claude/commands"
mkdir -p "$TARGET_DIR/.claude/rules"
echo -e "  ${GREEN}[done]${NC} .claude/commands/"
echo -e "  ${GREEN}[done]${NC} .claude/rules/"

# Copy .claude files
if [ -d "$TEMPLATE_DIR/.claude/rules" ]; then
    for rule_file in "$TEMPLATE_DIR/.claude/rules"/*.md; do
        if [ -f "$rule_file" ]; then
            filename=$(basename "$rule_file")
            copy_file "$rule_file" "$TARGET_DIR/.claude/rules/$filename" ".claude/rules/$filename"
        fi
    done
fi

# Ask about MCP config
echo ""
echo -e "${YELLOW}Do you want to include MCP server config template? (y/n)${NC}"
read -r include_mcp
if [[ "$include_mcp" =~ ^[Yy]$ ]]; then
    copy_file "$TEMPLATE_DIR/.mcp.json.example" "$TARGET_DIR/.mcp.json" ".mcp.json"
fi

# Update .gitignore
echo ""
echo -e "${BLUE}Updating .gitignore...${NC}"
GITIGNORE_ENTRIES="
# Claude Code local files
CLAUDE.local.md
.claude/settings.local.json
"

if [ -f "$TARGET_DIR/.gitignore" ]; then
    # Check if entries already exist
    if ! grep -q "CLAUDE.local.md" "$TARGET_DIR/.gitignore"; then
        echo "$GITIGNORE_ENTRIES" >> "$TARGET_DIR/.gitignore"
        echo -e "  ${GREEN}[done]${NC} Added Claude entries to .gitignore"
    else
        echo -e "  ${YELLOW}[skip]${NC} .gitignore already has Claude entries"
    fi
else
    echo "$GITIGNORE_ENTRIES" > "$TARGET_DIR/.gitignore"
    echo -e "  ${GREEN}[done]${NC} Created .gitignore with Claude entries"
fi

# Summary
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Project setup complete!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Edit CLAUDE.md with your project details"
echo "  2. Edit INFRASTRUCTURE.md with server info"
echo "  3. Edit _VOCABULARY.md with domain terms"
echo "  4. Review _FRAGILE.md for sensitive areas"
echo ""
echo -e "${YELLOW}Start a Claude session with:${NC}"
echo "  cd $TARGET_DIR && claude"
echo ""
echo -e "${YELLOW}Quick prompt:${NC}"
echo "  Read CLAUDE.md. Working on [your task]."
echo ""
