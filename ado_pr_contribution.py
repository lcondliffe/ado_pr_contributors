#!/usr/bin/env python3
"""
Azure DevOps PR Contribution Analysis using REST API

This script fetches and analyzes Pull Request data from Azure DevOps using the REST API.
It provides statistics on top authors, reviewers, and repositories for a given time period.

Usage:
    python pr_contribution_api.py [-v|-vv]                              # Current month, default project
    python pr_contribution_api.py [-v|-vv] "project_name"               # Current month, specific project
    python pr_contribution_api.py [-v|-vv] "project1,project2"          # Current month, multiple projects
    python pr_contribution_api.py [-v|-vv] 2025                         # Whole year, default project
    python pr_contribution_api.py [-v|-vv] 2025 1                       # Specific month, default project
    python pr_contribution_api.py [-v|-vv] "project_name" 2025          # Whole year, specific project
    python pr_contribution_api.py [-v|-vv] "project1,project2" 2025     # Whole year, multiple projects
    python pr_contribution_api.py [-v|-vv] "project_name" 2025 1        # Specific month, specific project
    python pr_contribution_api.py [-v|-vv] "project1,project2" 2025 1   # Specific month, multiple projects

Verbosity options:
    -v   Show progress information (e.g., "25/100 repos processed")
    -vv  Show detailed debug information (repository names, PR counts, etc.)
"""

import sys
import os
import requests
import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import subprocess
from typing import Dict, List, Optional, Tuple
import argparse

# Configuration
DEFAULT_PROJECT = "ic.cloud-core"
USE_CREATION_DATE = False  # Set to True to filter by creation date instead of completion date

# Global verbosity level (set by command line arguments)
VERBOSITY = 0  # 0 = silent, 1 = progress, 2 = debug

class AzureDevOpsAPI:
    def __init__(self, organization: str, project: str):
        self.organization = organization
        self.project = project
        self.base_url = f"https://dev.azure.com/{organization}/{project}/_apis"
        self.session = requests.Session()
        
        # Get access token from Azure CLI
        self._setup_authentication()
    
    def _setup_authentication(self):
        """Setup authentication using Azure CLI token"""
        try:
            # Try different resource URLs for Azure DevOps
            resources_to_try = [
                "499b84ac-1321-427f-aa17-267ca6975798",  # Azure DevOps
                "https://app.vssps.visualstudio.com/",   # Visual Studio Team Services
                "https://dev.azure.com/",                # Azure DevOps URL
            ]
            
            access_token = None
            for resource in resources_to_try:
                try:
                    if VERBOSITY >= 2:
                        print(f"Trying to get access token for resource: {resource}", file=sys.stderr)
                    
                    result = subprocess.run(
                        ["az", "account", "get-access-token", "--resource", resource],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    token_info = json.loads(result.stdout)
                    access_token = token_info['accessToken']
                    
                    if VERBOSITY >= 2:
                        print(f"✓ Successfully got access token using resource: {resource}", file=sys.stderr)
                    break
                    
                except subprocess.CalledProcessError as e:
                    if VERBOSITY >= 2:
                        print(f"Failed with resource {resource}: {e}", file=sys.stderr)
                    continue
            
            if not access_token:
                raise Exception("Could not obtain access token with any resource URL")
            
            # Set up session headers
            self.session.headers.update({
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            })
            
            if VERBOSITY >= 2:
                print("✓ Successfully authenticated with Azure DevOps", file=sys.stderr)
                
        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to get Azure CLI access token: {e}", file=sys.stderr)
            print("Make sure you're logged in with 'az login'", file=sys.stderr)
            print("You may also need to run: az devops configure --defaults organization=https://dev.azure.com/Next-Technology", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse Azure CLI token response: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    def get_repositories(self) -> List[Dict]:
        """Get all repositories in the project"""
        url = f"{self.base_url}/git/repositories"
        params = {"api-version": "7.0"}
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()['value']
        except requests.RequestException as e:
            print(f"Error fetching repositories: {e}", file=sys.stderr)
            return []
    
    def get_pull_requests(self, repository_id: str, skip: int = 0, top: int = 100) -> List[Dict]:
        """Get pull requests for a specific repository"""
        url = f"{self.base_url}/git/repositories/{repository_id}/pullrequests"
        params = {
            "api-version": "7.0",
            "searchCriteria.status": "completed",
            "$skip": skip,
            "$top": top
        }
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()['value']
        except requests.RequestException as e:
            # Handle specific HTTP status codes
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 404:
                    # 404 likely means repository doesn't support PRs or is archived
                    if VERBOSITY >= 2:
                        print(f"Repository {repository_id} does not support pull requests (404)", file=sys.stderr)
                    return []
                elif e.response.status_code == 403:
                    # 403 means access denied
                    if VERBOSITY >= 2:
                        print(f"Access denied to repository {repository_id} (403)", file=sys.stderr)
                    return []
                else:
                    # Other HTTP errors - show in verbose mode
                    if VERBOSITY >= 2:
                        print(f"Error fetching PRs for repository {repository_id}: {e}", file=sys.stderr)
                    return []
            else:
                # Network or other connection errors - always show these
                print(f"Network error fetching PRs for repository {repository_id}: {e}", file=sys.stderr)
                return []
    
    def get_all_pull_requests(self, start_date: str, end_date: str, use_creation_date: bool = False) -> List[Dict]:
        """Get all pull requests across all repositories in the project"""
        repositories = self.get_repositories()
        if VERBOSITY >= 2:
            print(f"Found {len(repositories)} repositories in project '{self.project}'", file=sys.stderr)
        
        all_prs = []
        total_fetched = 0
        repos_with_prs = 0
        repos_skipped = 0
        
        for i, repo in enumerate(repositories):
            repo_id = repo['id']
            repo_name = repo['name']
            
            if VERBOSITY >= 2:
                print(f"Fetching PRs from repository: {repo_name}", file=sys.stderr)
            elif VERBOSITY >= 1:
                print(f"\r{i+1}/{len(repositories)} repos processed", end='', file=sys.stderr)
            
            skip = 0
            batch_size = 100
            repo_pr_count = 0
            repo_has_data = False
            
            while True:
                prs = self.get_pull_requests(repo_id, skip, batch_size)
                
                # Check if this is the first successful call for this repo
                if prs and not repo_has_data:
                    repo_has_data = True
                
                if not prs:
                    break
                
                # Filter PRs by date
                filtered_prs = []
                for pr in prs:
                    date_field = pr['creationDate'] if use_creation_date else pr.get('closedDate')
                    
                    if date_field:
                        # Parse date and check if it's in range
                        # Handle different date formats from Azure DevOps API
                        try:
                            # Remove 'Z' and replace with '+00:00', handle microseconds
                            clean_date = date_field.replace('Z', '+00:00')
                            # If there are more than 6 digits in microseconds, truncate to 6
                            if '.' in clean_date and '+' in clean_date:
                                date_part, tz_part = clean_date.rsplit('+', 1)
                                if '.' in date_part:
                                    main_part, microseconds = date_part.rsplit('.', 1)
                                    if len(microseconds) > 6:
                                        microseconds = microseconds[:6]
                                    clean_date = f"{main_part}.{microseconds}+{tz_part}"
                            
                            pr_date = datetime.fromisoformat(clean_date).date()
                        except ValueError as e:
                            if VERBOSITY >= 2:
                                print(f"Warning: Could not parse date '{date_field}': {e}", file=sys.stderr)
                            continue
                        
                        start_dt = datetime.fromisoformat(start_date).date()
                        end_dt = datetime.fromisoformat(end_date).date()
                        
                        if start_dt <= pr_date < end_dt:
                            # Add repository name and project name to PR data
                            pr['repositoryName'] = repo_name
                            pr['projectName'] = self.project
                            filtered_prs.append(pr)
                
                all_prs.extend(filtered_prs)
                repo_pr_count += len(filtered_prs)
                total_fetched += len(prs)
                
                # If we got fewer PRs than requested, we've reached the end
                if len(prs) < batch_size:
                    break
                
                # Check if we should continue based on dates
                # If the newest PR in this batch is older than our start date, we can stop
                if prs and use_creation_date:
                    try:
                        newest_pr_date_str = prs[0]['creationDate']
                        clean_date = newest_pr_date_str.replace('Z', '+00:00')
                        if '.' in clean_date and '+' in clean_date:
                            date_part, tz_part = clean_date.rsplit('+', 1)
                            if '.' in date_part:
                                main_part, microseconds = date_part.rsplit('.', 1)
                                if len(microseconds) > 6:
                                    microseconds = microseconds[:6]
                                clean_date = f"{main_part}.{microseconds}+{tz_part}"
                        
                        newest_pr_date = datetime.fromisoformat(clean_date).date()
                        if newest_pr_date < datetime.fromisoformat(start_date).date():
                            break
                    except ValueError:
                        # If we can't parse the date, continue fetching
                        pass
                
                skip += batch_size
            
            # Count repos with PRs found
            if repo_pr_count > 0:
                repos_with_prs += 1
                if VERBOSITY >= 2:
                    print(f"  Found {repo_pr_count} PRs in date range from {repo_name}", file=sys.stderr)
            elif not repo_has_data:
                repos_skipped += 1
        
        if VERBOSITY >= 1:
            # Clear the progress line and print summary
            print(f"\r{len(repositories)}/{len(repositories)} repos processed", file=sys.stderr)
            
        if VERBOSITY >= 2:
            print(f"Total PRs fetched: {total_fetched}, Filtered to date range: {len(all_prs)}", file=sys.stderr)
            print(f"Repositories with PRs: {repos_with_prs}, Repositories skipped: {repos_skipped}", file=sys.stderr)
        elif VERBOSITY >= 1 and repos_skipped > 0:
            print(f"Note: {repos_skipped} repositories were skipped (no PR support or access denied)", file=sys.stderr)
        
        return all_prs

def parse_arguments() -> Tuple[List[str], Optional[str], Optional[str], bool, bool]:
    """Parse command line arguments"""
    global VERBOSITY
    
    # Remove verbosity flags from arguments and set verbosity level
    args = []
    for arg in sys.argv[1:]:
        if arg == '-vv':
            VERBOSITY = 2
        elif arg == '-v':
            VERBOSITY = 1
        else:
            args.append(arg)
    
    # Reassign sys.argv to process remaining arguments
    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0]] + args
    
    try:
        if len(sys.argv) == 1:
            # No arguments: Default project, current month
            return [DEFAULT_PROJECT], None, None, True, False
        elif len(sys.argv) == 2:
            # One argument: could be project name(s) or year
            arg = sys.argv[1]
            # Try to parse as year first
            try:
                year_int = int(arg)
                if 2000 <= year_int <= 2030:
                    # It's a year: default project, specific year
                    return [DEFAULT_PROJECT], arg, None, False, True
            except ValueError:
                pass
            # It's a project name or comma-separated project names: specific project(s), current month
            projects = [p.strip() for p in arg.split(',')]
            return projects, None, None, True, False
        elif len(sys.argv) == 3:
            # Two arguments: could be project(s)+year or year+month
            arg1, arg2 = sys.argv[1], sys.argv[2]
            # Try to parse first arg as year
            try:
                year_int = int(arg1)
                if 2000 <= year_int <= 2030:
                    # First arg is year, check if second is month
                    try:
                        month_int = int(arg2)
                        if 1 <= month_int <= 12:
                            # year and month: default project, specific year and month
                            return [DEFAULT_PROJECT], arg1, arg2, False, False
                    except ValueError:
                        pass
            except ValueError:
                pass
            
            # Try to parse second arg as year (project(s) + year)
            try:
                year_int = int(arg2)
                if 2000 <= year_int <= 2030:
                    # project(s) and year: specific project(s), specific year
                    projects = [p.strip() for p in arg1.split(',')]
                    return projects, arg2, None, False, True
            except ValueError:
                pass
            
            # If neither interpretation works, show error
            print("Error: Invalid arguments. Second argument should be a year (YYYY) or the arguments should be year (YYYY) and month (MM).", file=sys.stderr)
            print("Usage:", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv]                         # Current month, default project ({DEFAULT_PROJECT})", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project_name>\"         # Current month, specific project", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project1,project2>\"    # Current month, multiple projects", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] <YYYY>                  # Whole year, default project ({DEFAULT_PROJECT})", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] <YYYY> <MM>             # Specific month, default project ({DEFAULT_PROJECT})", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project_name>\" <YYYY>  # Whole year, specific project", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project1,project2>\" <YYYY>  # Whole year, multiple projects", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project_name>\" <YYYY> <MM>  # Specific month, specific project", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project1,project2>\" <YYYY> <MM>  # Specific month, multiple projects", file=sys.stderr)
            print("", file=sys.stderr)
            print("Verbosity options:", file=sys.stderr)
            print("  -v   Show progress information", file=sys.stderr)
            print("  -vv  Show detailed debug information", file=sys.stderr)
            sys.exit(1)
        elif len(sys.argv) == 4:
            # Three arguments: specific project(s), specific year and month
            projects = [p.strip() for p in sys.argv[1].split(',')]
            return projects, sys.argv[2], sys.argv[3], False, False
        else:
            print("Usage:", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv]                         # Current month, default project ({DEFAULT_PROJECT})", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project_name>\"         # Current month, specific project", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project1,project2>\"    # Current month, multiple projects", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] <YYYY>                  # Whole year, default project ({DEFAULT_PROJECT})", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] <YYYY> <MM>             # Specific month, default project ({DEFAULT_PROJECT})", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project_name>\" <YYYY>  # Whole year, specific project", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project1,project2>\" <YYYY>  # Whole year, multiple projects", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project_name>\" <YYYY> <MM>  # Specific month, specific project", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] \"<project1,project2>\" <YYYY> <MM>  # Specific month, multiple projects", file=sys.stderr)
            print("", file=sys.stderr)
            print("Verbosity options:", file=sys.stderr)
            print("  -v   Show progress information", file=sys.stderr)
            print("  -vv  Show detailed debug information", file=sys.stderr)
            sys.exit(1)
    finally:
        # Restore original sys.argv
        sys.argv = original_argv

def validate_year_input(year: str) -> str:
    """Validate and format year input"""
    try:
        year_int = int(year)
        
        if year_int < 2000 or year_int > 2030:
            raise ValueError(f"Invalid year: {year}")
        
        return f"{year_int:04d}"
    
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Use YYYY for year (e.g., 2024)", file=sys.stderr)
        sys.exit(1)

def validate_date_inputs(year: str, month: str) -> Tuple[str, str]:
    """Validate and format year and month inputs"""
    try:
        year_int = int(year)
        month_int = int(month)
        
        if year_int < 2000 or year_int > 2030:
            raise ValueError(f"Invalid year: {year}")
        
        if month_int < 1 or month_int > 12:
            raise ValueError(f"Invalid month: {month}")
        
        return f"{year_int:04d}", f"{month_int:02d}"
    
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Use YYYY for year (e.g., 2024) and M or MM for month (e.g., 7, 07, 12)", file=sys.stderr)
        sys.exit(1)

def get_date_range(year: Optional[str], month: Optional[str], use_current_month: bool, use_whole_year: bool) -> Tuple[str, str, str]:
    """Calculate start and end dates for the analysis period"""
    if use_current_month:
        # Current month to date
        now = datetime.now()
        start_date = now.replace(day=1).strftime('%Y-%m-%d')
        end_date = (now + timedelta(days=1)).strftime('%Y-%m-%d')  # Include today
        period_desc = f"for the current month ({now.strftime('%Y-%m')}) up to today"
    elif use_whole_year:
        # Whole year
        year_formatted = validate_year_input(year)
        start_date = f"{year_formatted}-01-01"
        end_date = f"{int(year_formatted) + 1:04d}-01-01"  # Start of next year
        period_desc = f"for the year {year_formatted}"
    else:
        # Specific month and year
        year_formatted, month_formatted = validate_date_inputs(year, month)
        start_date = f"{year_formatted}-{month_formatted}-01"
        
        # Calculate end of month
        if month_formatted == "12":
            next_month = f"{int(year_formatted) + 1:04d}-01-01"
        else:
            next_month = f"{year_formatted}-{int(month_formatted) + 1:02d}-01"
        
        end_date = next_month
        period_desc = f"for {year_formatted}-{month_formatted}"
    
    return start_date, end_date, period_desc

def analyze_pr_data(prs: List[Dict]) -> Dict:
    """Analyze PR data and generate statistics"""
    authors = Counter()
    reviewers = Counter()
    repositories = Counter()
    projects = Counter()
    
    for pr in prs:
        # Count authors
        author = pr.get('createdBy', {}).get('displayName', 'Unknown')
        authors[author] += 1
        
        # Count reviewers
        for reviewer in pr.get('reviewers', []):
            reviewer_name = reviewer.get('displayName', 'Unknown')
            # Filter out service accounts
            if not reviewer_name.startswith('[') and 'Cloud Services' not in reviewer_name:
                reviewers[reviewer_name] += 1
        
        # Count repositories
        repo_name = pr.get('repositoryName', 'Unknown')
        repositories[repo_name] += 1
        
        # Count projects
        project_name = pr.get('projectName', 'Unknown')
        projects[project_name] += 1
    
    return {
        'authors': authors.most_common(10),
        'reviewers': reviewers.most_common(10),
        'repositories': repositories.most_common(10),
        'projects': projects.most_common(),
        'total_prs': len(prs)
    }

def print_results(stats: Dict, projects: List[str], period_desc: str, use_creation_date: bool):
    """Print the analysis results"""
    date_field_desc = "created" if use_creation_date else "completed"
    
    print()
    if len(projects) == 1:
        print(f"### Overall PR Contributions {period_desc} for Project '{projects[0]}'")
    else:
        project_names = "', '".join(projects)
        print(f"### Overall PR Contributions {period_desc} for Projects '{project_names}'")
    print()
    
    # Show project breakdown if multiple projects
    if len(projects) > 1 and 'projects' in stats:
        print("Project breakdown:")
        for project, count in stats['projects']:
            print(f"  {project}: {count} PRs")
        print()
    
    # Top authors
    print("Top 10 authors:")
    for author, count in stats['authors']:
        print(f"  {author}: {count} PRs")
    print()
    
    # Top reviewers
    print("Top 10 reviewers:")
    for reviewer, count in stats['reviewers']:
        print(f"  {reviewer}: {count} reviews")
    print()
    
    # Top repositories
    print("Top 10 repos by PR activity:")
    for repo, count in stats['repositories']:
        print(f"  {repo}: {count} PRs")

def get_organization_from_azure_cli() -> str:
    """Get the Azure DevOps organization from Azure CLI configuration"""
    try:
        # First try to get from Azure DevOps CLI configuration
        result = subprocess.run(
            ["az", "devops", "configure", "--list"],
            capture_output=True,
            text=True,
            check=True
        )
        
        for line in result.stdout.strip().split('\n'):
            if 'organization' in line and '=' in line:
                org_url = line.split('=')[1].strip()
                # Extract organization name from URL
                if 'dev.azure.com/' in org_url:
                    return org_url.split('dev.azure.com/')[1].rstrip('/')
                return org_url
        
        # If no organization configured, try to get from git remote
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            url = result.stdout.strip()
            if 'dev.azure.com' in url:
                # Extract organization from URL like: https://dev.azure.com/organization/project/_git/repo
                parts = url.split('dev.azure.com/')[1].split('/')
                if parts:
                    return parts[0]
        
        # Default fallback based on current context
        print("Warning: Could not determine Azure DevOps organization from configuration", file=sys.stderr)
        print("Trying to use 'Next-Technology' as default organization", file=sys.stderr)
        return "Next-Technology"
        
    except subprocess.CalledProcessError:
        print("Warning: Could not determine Azure DevOps organization, using default 'Next-Technology'", file=sys.stderr)
        return "Next-Technology"

def fetch_prs_from_multiple_projects(organization: str, projects: List[str], start_date: str, end_date: str, use_creation_date: bool) -> List[Dict]:
    """Fetch PRs from multiple projects and combine the results"""
    all_prs = []
    
    if VERBOSITY >= 1:
        print(f"Fetching data from {len(projects)} project(s)...", file=sys.stderr)
    
    for i, project in enumerate(projects):
        if VERBOSITY >= 2:
            print(f"Fetching data from project '{project}' ({i+1}/{len(projects)})...", file=sys.stderr)
        elif VERBOSITY >= 1:
            print(f"\rProject {i+1}/{len(projects)}: {project}", end='', file=sys.stderr)
        
        try:
            # Initialize API client for this project
            api = AzureDevOpsAPI(organization, project)
            
            # Fetch PR data for this project
            project_prs = api.get_all_pull_requests(start_date, end_date, use_creation_date)
            all_prs.extend(project_prs)
            
            if VERBOSITY >= 2:
                print(f"  Found {len(project_prs)} PRs from project '{project}'", file=sys.stderr)
                
        except Exception as e:
            print(f"\nWarning: Failed to fetch data from project '{project}': {e}", file=sys.stderr)
            if VERBOSITY >= 2:
                import traceback
                traceback.print_exc(file=sys.stderr)
            continue
    
    if VERBOSITY >= 1:
        print(f"\rCompleted fetching from {len(projects)} project(s)", file=sys.stderr)
        if len(projects) > 1:
            print(f"Total PRs found across all projects: {len(all_prs)}", file=sys.stderr)
    
    return all_prs

def main():
    """Main execution function"""
    # Parse arguments
    projects, year, month, use_current_month, use_whole_year = parse_arguments()
    
    # Get date range
    start_date, end_date, period_desc = get_date_range(year, month, use_current_month, use_whole_year)
    
    # Get organization
    organization = get_organization_from_azure_cli()
    
    if VERBOSITY >= 2:
        date_type = "creation" if USE_CREATION_DATE else "completion"
        if len(projects) == 1:
            print(f"Using project '{projects[0]}' and data {period_desc}", file=sys.stderr)
        else:
            project_names = "', '".join(projects)
            print(f"Using projects '{project_names}' and data {period_desc}", file=sys.stderr)
        print(f"Fetching PR data between {start_date} and {end_date} (by {date_type} date)...", file=sys.stderr)
        print(f"Organization: {organization}", file=sys.stderr)
    
    # Fetch PR data from all projects
    try:
        if len(projects) == 1:
            # Single project - use existing logic
            api = AzureDevOpsAPI(organization, projects[0])
            prs = api.get_all_pull_requests(start_date, end_date, USE_CREATION_DATE)
        else:
            # Multiple projects - use new aggregation function
            prs = fetch_prs_from_multiple_projects(organization, projects, start_date, end_date, USE_CREATION_DATE)
        
        if not prs:
            project_names = "', '".join(projects)
            print(f"No completed PRs found for the specified period ({start_date} to {end_date}) in project(s) '{project_names}'.")
            print("This could be because:")
            if USE_CREATION_DATE:
                print("  1. No PRs were created in this period")
                print("  2. PRs exist but were created outside this date range")
            else:
                print("  1. No PRs were completed (merged/closed) in this period")
                print("  2. PRs exist but were created in this period and completed later")
            print("  3. API access limitations or project name mismatch")
            print("Suggestion: Try using a more recent date range, toggle creation vs completion date filtering, or verify the project name(s).")
            return
        
        # Analyze data
        stats = analyze_pr_data(prs)
        
        # Print results
        print_results(stats, projects, period_desc, USE_CREATION_DATE)
        
    except Exception as e:
        print(f"Error: Failed to fetch or process PR data: {e}", file=sys.stderr)
        if VERBOSITY >= 2:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()