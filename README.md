# Azure DevOps PR Contribution Analysis

A Python script that fetches and analyzes Pull Request data from Azure DevOps using the REST API. It provides statistics on top authors, reviewers, and repositories for a given time period.

## Features

- Analyze PR contributions by authors, reviewers, and repositories
- Support for single or multiple project analysis
- Flexible time period selection (current month, specific month, or entire year)
- Support for both PR creation date and completion date filtering
- Progress tracking with configurable verbosity levels
- Automatic Azure CLI authentication
- Cross-repository analysis within a project or across multiple projects

## Prerequisites

- Python 3.6+
- Azure CLI installed and configured
- Access to the Azure DevOps organization and project
- Logged in via `az login`

## Installation

1. Clone this repository or download the script
2. Ensure Azure CLI is installed and you're logged in:
   ```bash
   az login
   az devops configure --defaults organization=https://dev.azure.com/YourOrganization
   ```

## Usage

The script supports various usage patterns with optional verbosity flags:

### Basic Usage
```bash
# Current month, default project
python ado_pr_contribution.py

# Current month, specific project
python ado_pr_contribution.py "project_name"

# Current month, multiple projects
python ado_pr_contribution.py "project1,project2,project3"

# Whole year, default project
python ado_pr_contribution.py 2024

# Specific month, default project
python ado_pr_contribution.py 2024 7

# Whole year, specific project
python ado_pr_contribution.py "project_name" 2024

# Whole year, multiple projects
python ado_pr_contribution.py "project1,project2" 2024

# Specific month, specific project
python ado_pr_contribution.py "project_name" 2024 7

# Specific month, multiple projects
python ado_pr_contribution.py "project1,project2" 2024 7
```

### Verbosity Options
```bash
# Show progress information
python ado_pr_contribution.py -v

# Show detailed debug information
python ado_pr_contribution.py -vv "project_name" 2024

# Multiple projects with verbosity
python ado_pr_contribution.py -vv "project1,project2" 2024
```

### Multiple Projects

When specifying multiple projects, separate them with commas:
- `"ic.cloud-core,spt.backlog"` - Two projects
- `"project1,project2,project3"` - Three projects
- Spaces around commas are automatically trimmed

The script will fetch data from all specified projects and aggregate the results into combined statistics.

## Configuration

You can modify the following configuration variables at the top of the script:

- `DEFAULT_PROJECT`: Set your default project name
- `USE_CREATION_DATE`: Toggle between PR creation date (True) or completion date (False) for filtering

## Output

The script provides:

1. **Top 10 Authors**: Contributors with the most PRs across all specified projects
2. **Top 10 Reviewers**: People who reviewed the most PRs across all specified projects
3. **Top 10 Repositories**: Repos with the most PR activity across all specified projects
4. **Project Breakdown**: When analyzing multiple projects, shows PR count per project
5. **Total PR Count**: Overall number of PRs in the specified period across all projects

### Sample Output

#### Single Project
```
### Overall PR Contributions for 2024-07 for Project 'my-project'

Top 10 authors:
  John Doe: 15 PRs
  Jane Smith: 12 PRs
  ...

Top 10 reviewers:
  Alice Johnson: 25 reviews
  Bob Wilson: 18 reviews
  ...

Top 10 repos by PR activity:
  frontend-app: 20 PRs
  backend-api: 15 PRs
  ...
```

#### Multiple Projects
```
### Overall PR Contributions for 2024-07 for Projects 'ic.cloud-core', 'spt.backlog'

Project breakdown:
  ic.cloud-core: 45 PRs
  spt.backlog: 23 PRs

Top 10 authors:
  John Doe: 18 PRs
  Jane Smith: 15 PRs
  ...

Top 10 reviewers:
  Alice Johnson: 30 reviews
  Bob Wilson: 22 reviews
  ...

Top 10 repos by PR activity:
  frontend-app: 25 PRs
  backend-api: 20 PRs
  ...
```

## Authentication

The script uses Azure CLI for authentication. It automatically tries multiple resource URLs to obtain the access token:
- Azure DevOps resource ID
- Visual Studio Team Services URL
- Azure DevOps URL

Make sure you're logged in with appropriate permissions to access the Azure DevOps project.

## Error Handling

The script handles common scenarios:
- Repositories without PR support (returns 404)
- Access denied to specific repositories (returns 403)
- Network connectivity issues
- Invalid date formats from the API
- Missing or invalid command line arguments
- Failed access to individual projects (continues with remaining projects)

## Limitations

- Only analyzes completed/merged PRs
- Filters out service accounts (names starting with '[' or containing 'Cloud Services')
- Requires appropriate Azure DevOps permissions
- Limited to 10 results per category in output

## Contributing

Feel free to submit issues or pull requests to improve the script.

## License

This project is open source and available under the [MIT License](LICENSE).
