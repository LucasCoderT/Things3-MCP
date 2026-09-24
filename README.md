<div align="center">

![Things3 MCP Logo](https://github.com/rossshannon/Things3-MCP/raw/main/docs/images/Things3-MCP-logo.png)

# Things 3 MCP Server

</div>

This [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) server lets you use Claude Desktop to interact with your task management data in [Things 3](https://culturedcode.com/things). You can ask Claude or your MCP client of choice to create tasks, analyze projects, help manage priorities, and more.

This MCP server leverages a combination of the [Things.py](https://github.com/thingsapi/things.py) library and [Things 3’s AppleScript support](https://culturedcode.com/things/support/articles/4562654/), enabling reading and writing to Things 3.

## Why Things MCP?

This MCP server unlocks the power of AI for your task management:

- **Natural Language Task Creation**: Ask Claude to create richly-detailed tasks and descriptions in natural language
- **Smart Task Analysis**: Let Claude explore your project lists and focus areas and provide insights into your work
- **GTD & Productivity Workflows**: Let Claude help you implement productivity and prioritisation systems
- **Seamless Integration**: Works directly with your existing Things 3 data

## Features

- Access to all major Things lists (Inbox, Today, Upcoming, Logbook, Someday, etc.)
- Project and Area management and assignment
- Tagging operations for tasks and projects
- Advanced search capabilities
- Recent items tracking
- Support for nested data (projects within areas, todos within projects)
- Checklist/Subtask support - Read and display existing checklist items from todos

## Installation

#### Prerequisites
* Python 3.12+
* Claude Desktop
* Things 3 for MacOS

#### Step 1: Install the package

**Option A: Install from PyPI in a virtual environment (recommended)**
```bash
# Create a virtual environment in your home directory
python3 -m venv ~/.venvs/things3-mcp-env
source ~/.venvs/things3-mcp-env/bin/activate

# Install the package
pip install Things3-MCP-server==2.0.6
```

**Option B: Install from source (for development/contributors)**
```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh
# Restart your terminal afterwards

# Clone and install the package with development dependencies
git clone https://github.com/rossshannon/Things3-MCP
cd Things3-MCP
uv venv
uv pip install -e ".[dev]"  # Install in development mode with extra dependencies
```

### Step 2: Configure Claude Desktop
Edit the Claude Desktop configuration file:
```bash
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Add the Things server to the mcpServers key in the configuration file:

**Option A: Using PyPI package in virtual environment**
```json
{
    "mcpServers": {
        "things": {
            "command": "~/.venvs/things3-mcp-env/bin/Things3-MCP-server"
        }
    }
}
```

**Option B: Using source installation (for development/contributors)**
```json
{
    "mcpServers": {
        "things": {
            "command": "uv",
            "args": [
                "--directory",
                "/ABSOLUTE/PATH/TO/PARENT/FOLDER/Things3-MCP",
                "run",
                "Things3-MCP-server"
            ]
        }
    }
}
```

### Step 3: Restart Claude Desktop
Restart the Claude Desktop app to enable the integration.

### Sample Usage with Claude Desktop
* “What’s on my todo list today?”
* “Create a todo to prepare for each of my 1-on-1s next week”
* “Evaluate my todos scheduled for today using the Eisenhower matrix.”
* “Help me conduct a GTD-style weekly review using Things.”

#### Tips
* Create a Project in Claude with custom instructions that explains how you use Things and organize areas, projects, tags, etc. Tell Claude what information you want included when it creates a new task (e.g., asking it to include relevant details in the task description, whether to use emojis, etc.).
* Try combining this with another MCP server that gives Claude access to your calendar. This will let you ask Claude to block time on your calendar for specific tasks, create tasks that relate to upcoming calendar events (e.g., prep for a meeting), etc.


### Available Tools

#### List Views
- `get_inbox` - Get todos from Inbox
- `get_today` - Get todos due today
- `get_upcoming` - Get upcoming todos
- `get_anytime` - Get todos from Anytime list
- `get_someday` - Get todos from Someday list
- `get_logbook` - Get completed todos
- `get_trash` - Get trashed todos

#### Random Sampling (for LLM Enrichment)
- `get_random_inbox` - Get a random sample of todos from Inbox
- `get_random_anytime` - Get a random sample of items from Anytime list
- `get_random_todos` - Get a random sample of todos, optionally filtered by project

#### Basic Operations
- `get_todos` - Get todos, optionally filtered by project
- `get_headings` - Get the headings in a project
- `get_projects` - Get all projects
- `get_areas` - Get all areas

#### Tag Operations
- `get_tags` - Get all tags
- `get_tagged_items` - Get items with a specific tag

#### Search Operations
- `search_todos` - Simple search by title/notes
- `search_advanced` - Advanced search with multiple filters

#### Time-based Operations
- `get_recent` - Get recently created items

#### Modification Operations
- `add_todo` - Create a new todo with full parameter support
- `add_project` - Create a new project with tags and todos
- `update_todo` - Update an existing todo
- `update_project` - Update an existing project
- `show_item` - Show a specific item or list in Things
- `search_items` - Search for items in Things

## Tool Parameters

### get_todos
- `project_uuid` (optional) - Filter todos by project. With a project, todos come back in the same order as the app: the ones without a heading first, then each heading's todos in heading order. Each todo under a heading has a `Heading:` line

### get_headings
- `project_uuid` - Project to list headings for. Returns each heading's title and UUID in display order

### get_projects / get_areas / get_tags
- `include_items` (optional, default: false) - Include contained items

### search_advanced
- `status` - Filter by status (incomplete/completed/canceled)
- `start_date` - Filter by start date (YYYY-MM-DD)
- `deadline` - Filter by deadline (YYYY-MM-DD)
- `tag` - Filter by tag
- `area` - Filter by area UUID
- `type` - Filter by item type (to-do/project/heading)

### get_recent
- `period` - Time period (e.g., '3d', '1w', '2m', '1y')
- `limit` - Maximum number of items to return

### Random Sampling Tools
- `get_random_inbox(count=5)` - Get random sample from Inbox
- `get_random_anytime(count=5)` - Get random sample from Anytime list
- `get_random_todos(project_uuid=None, count=5)` - Get random sample of todos, optionally from specific project

### add_todo
- `title` - Title of the todo
- `notes` (optional) - Notes for the todo (supports Markdown formatting including checkboxes like `- [ ] Task`)
- `when` (optional) - When to schedule the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD), optionally with a reminder time like `today@18:00`. See [Reminders and This Evening](#reminders-and-this-evening)
- `deadline` (optional) - Deadline for the todo (YYYY-MM-DD)
- `tags` (optional) - Tags to apply to the todo
- `list_title` (optional) - Title of project/area to add to (must exactly match existing name)
- `list_id` (optional) - ID of project/area to add to (takes priority over list_title if both provided)
- `checklist_items` (optional) - Native Things checklist items, one per array entry (max 100, no newlines inside an item). Needs `THINGS_AUTH_TOKEN`
- `heading` (optional) - Title of an existing heading in the target project (case-insensitive). Needs `list_id` or `list_title` pointing at a project, and `THINGS_AUTH_TOKEN`. See [Headings](#headings)
- **Note**: Native checklist items can't be created through AppleScript, so `checklist_items` goes through the Things URL scheme and needs the auth token (see [Reminders and This Evening](#reminders-and-this-evening)). Without the token, you can still use Markdown checkboxes in the notes field for something similar. ![Things3 - Subtasks - Markdown Checklist](docs/images/Things3-subtasks-markdown-checklist.png)

### update_todo
- `id` - ID of the todo to update
- `title` (optional) - New title
- `notes` (optional) - New notes. `""` clears them
- `when` (optional) - When to schedule the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD), optionally with a reminder time like `today@18:00`. See [Reminders and This Evening](#reminders-and-this-evening)
- `deadline` (optional) - Deadline for the todo (YYYY-MM-DD)
- `tags` (optional) - New tags, replacing the existing ones. `[]` removes them all
- `completed` (optional) - Mark as completed
- `canceled` (optional) - Mark as canceled
- `list_name` (optional) - Name of built-in list, project, or area to move the todo to. For built-in lists use: "Inbox", "Today", "Anytime", "Someday". For projects/areas, use the exact name.
- `list_id` (optional) - ID of project/area to move the todo to (takes priority over list_name if both provided)
- `checklist_items` (optional) - Native Things checklist items, one per array entry (max 100, no newlines inside an item). Needs `THINGS_AUTH_TOKEN`
- `checklist_mode` (optional) - `replace` (default), `append` or `prepend`, for how `checklist_items` combine with the existing checklist
- `heading` (optional) - Title of an existing heading to move the todo under (case-insensitive), checked against the new project if the todo is being moved, otherwise its current one. `""` moves it out of its heading. Needs `THINGS_AUTH_TOKEN`

### add_project
- `title` - Title of the project
- `notes` (optional) - Notes for the project
- `when` (optional) - When to schedule the project
- `deadline` (optional) - Deadline for the project
- `tags` (optional) - Tags to apply to the project
- `area_title` or `area_id` (optional) - Title or ID of area to add to (must exactly match an existing area title — look them up with `get_areas`)
- `todos` (optional) - Initial todos to create in the project

### update_project
- `id` - ID of the project to update
- `title` (optional) - New title
- `notes` (optional) - New notes. `""` clears them
- `when` (optional) - When to schedule the project (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
- `deadline` (optional) - Deadline for the project (YYYY-MM-DD)
- `tags` (optional) - New tags, replacing the existing ones. `[]` removes them all
- `completed` (optional) - Mark as completed
- `canceled` (optional) - Mark as canceled

### show_item
- `id` - ID of item to show, or one of: inbox, today, upcoming, anytime, someday, logbook
- `query` (optional) - Optional query to filter by
- `filter_tags` (optional) - Optional tags to filter by

## Usage Examples

### Creating Todos with List Assignment

```python
# Create todo in Inbox (default)
add_todo(title="Review quarterly report")

# Create todo in a built-in list
add_todo(title="Call dentist", when="today")
add_todo(title="Plan vacation", when="someday")

# Create todo in a project by name
add_todo(title="Design new logo", list_title="Website Redesign")

# Create todo in a project by ID (more precise, recommended for automation)
add_todo(title="Write documentation", list_id="ABC123DEF456")

# When both are provided, list_id takes priority
add_todo(
    title="Important task",
    list_id="ABC123DEF456",     # This will be used
    list_title="Other Project"  # This will be ignored
)
```

### Moving Todos Between Lists

```python
# Move to built-in list
update_todo(id="TODO123", list_name="Today")
update_todo(id="TODO456", list_name="Someday")

# Move to project by name
update_todo(id="TODO789", list_name="Website Redesign")

# Move to project by ID (recommended for precision)
update_todo(id="TODO101", list_id="ABC123DEF456")
```

### When to Use ID vs Title

- **Use `list_title`/`list_name`** when:
  - Working interactively with human-readable names
  - You're certain the name is unique and won't change
  - Creating simple scripts or one-off tasks

- **Use `list_id`** when:
  - Building automation or applications
  - You need precision and reliability
  - Working with projects/areas that might have similar names

## Using Tags
Things will automatically create missing tags when they are added to a task or project. Configure your LLM to do a lookup of your tags first before making changes if you want to control this.

## LLM Enrichment Workflows

The random sampling tools (`get_random_inbox`, `get_random_anytime`, `get_random_todos`) are designed for iterative task improvement workflows where you want to gradually enhance your todo items using AI assistance.

### Use Cases

**Incremental Task Enhancement**
- Pull 5 random todos from your Inbox to add better descriptions, break down into subtasks, or estimate time requirements
- Sample from your Anytime list to identify tasks that could benefit from better scheduling or prioritization
- Avoid downloading hundreds of tasks into context when you only need a few

**Content Enrichment**
- Add or improve context and suggest more actionable language
- Add context, dependencies, or next steps to existing todos
- Standardize formatting across your task descriptions
- Find tasks that might be too vague or overly complex
- Discover todos that could be automated or delegated

## Reminders and This Evening

AppleScript can only give Things a date, so it can't put a todo in This Evening or set a reminder time. For those, `add_todo` and `update_todo` create or update the todo with AppleScript first and then send the rest through the Things URL scheme. That needs your Things auth token, which is in Things → Settings → General → Enable Things URLs → Manage.

Put it in the `env` block for the server in `claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "things": {
            "command": "~/.venvs/things3-mcp-env/bin/Things3-MCP-server",
            "env": {
                "THINGS_AUTH_TOKEN": "your-token-here"
            }
        }
    }
}
```

The same token is used for `checklist_items`, which puts real Things checklist items on a todo. The reminder and checklist parts go to Things together in one URL.

Some `when` values that use it:

- `evening` puts the todo in This Evening
- `today@18:00` or `today@6pm` for a reminder later today
- `tomorrow@9am`
- `2026-10-01@14:30` for a date and time
- `evening@9:30pm` for This Evening with a reminder

Times can be 24-hour (`18:00`) or 12-hour with am/pm (`6pm`, `6:30 PM`). `anytime` and `someday` can't take a time, and the tool returns an error without creating anything. Plain values like `today` or `2026-10-01` don't need the token at all.

If the token is missing, the todo still gets created with its date, and the tool tells you the reminder part didn't go through.

A wrong token is harder to spot, because Things only shows that error in its own window. So after sending the URL, the tool reads the todo back for up to 5 seconds and warns you if the change never showed up.

Reads show the result too. Todos with a reminder get a `Reminder: 18:00` line, and todos in This Evening get `Evening: yes`. Neither is in things.py, so these two come straight from the Things database, opened read-only.

Repeating todos have to be set up in the Things app itself. Neither AppleScript nor the URL scheme can create them.

## Headings

Headings are the groups inside a project. `get_headings` lists them, and `add_todo` and `update_todo` take a `heading` to put a todo under one. Like reminders, this goes through the URL scheme and needs the same token.

The heading is checked before anything is written. If it isn't in the project, or more than one heading matches, or the todo isn't going into a project at all, you get an error listing the project's headings and nothing is created or changed.

Headings themselves have to be created in the Things app, with Cmd-Shift-N inside a project.

I tried adding one to an existing project through `things:///json` with an `update` operation, but Things ignored it.

## Development

This project uses `pyproject.toml` to manage dependencies and build configuration. It's built using the [Model Context Protocol](https://modelcontextprotocol.io), which allows Claude to securely access tools and data.

### Development Workflow

#### Setting up a development environment

```bash
# Clone the repository
git clone https://github.com/rossshannon/Things3-MCP
cd Things3-MCP

# Set up a virtual environment with development dependencies
uv venv
uv pip install -e ".[dev]"  # Install in development mode with extra dependencies
```

#### Testing changes during development

Run the comprehensive test suite to ensure everything is working as expected:

```bash
# Run all tests (116 tests, ~3-4 minutes)
uv run pytest

# Run tests with coverage report
uv run pytest --cov=things3_mcp --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_list_assignment_operations.py

# Run tests with minimal output
uv run pytest -q

# Run tests matching a pattern
uv run pytest -k "error_handling"
```

**Test Configuration:**
- **116 comprehensive tests** covering all functionality
- **Automatic cleanup** - tests don't affect your existing Things data
- **Edge case coverage** - malformed UUIDs, timeouts, error conditions
- **Integration testing** - tests against real Things app

The tests clean up after themselves and don't affect your existing data, so you can run them as often as you like.

![Things 3 MCP Test Suite](https://github.com/rossshannon/Things3-MCP/raw/main/docs/images/Things3-mcp-test-suite.png)

## Troubleshooting

The server includes error handling for:
- Invalid UUIDs
- Missing required parameters
- Things database access errors
- Data formatting errors
- Authentication token issues
- AppleScript execution failures

### Common Issues

1. **Things app not running**: Make sure the Things app is running on your Mac for AppleScript methods to work.

### Checking Logs

All errors are logged and returned with descriptive messages. To review the MCP logs:

```bash
# Follow main logs in real-time
tail -f ~/.things-mcp/logs/things3_mcp.log

# Check error logs
tail -f ~/.things-mcp/logs/things3_mcp_errors.log

# View structured logs for analysis
cat ~/.things-mcp/logs/things3_mcp_structured.json | jq

# Claude Desktop MCP logs
tail -n 20 -f ~/Library/Logs/Claude/mcp*.log
```

## Acknowledgements

This MCP server was originally based on the Applescript bridge method from [things-mcp](https://github.com/excelsier/things-fastmcp) by [excelsier](https://github.com/excelsier/), which was in turn based on [things-mcp](https://github.com/hald/things-mcp) by [hald](https://github.com/hald/).
