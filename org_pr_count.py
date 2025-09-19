#!/usr/bin/env python3
"""
Azure DevOps Organization PR Count Analysis using REST API

This script fetches and counts Pull Request data from all projects in an Azure DevOps organization.
It provides total PR counts and per-project breakdown for a given time period.

Usage:
    python org_pr_count.py [-v|-vv]             # Current month
    python org_pr_count.py [-v|-vv] 2025        # Whole year 2025
    python org_pr_count.py [-v|-vv] 2025 5      # May 2025

Verbosity options:
    -v   Show progress information (e.g., "25/100 projects processed")
    -vv  Show detailed debug information (project names, PR counts, etc.)
"""

import sys
import os
import requests
import json
from datetime import datetime, timedelta
from collections import Counter
import subprocess
from typing import Dict, List, Optional, Tuple

# Configuration
USE_CREATION_DATE = False  # Set to True to filter by creation date instead of completion date

# Global verbosity level (set by command line arguments)
VERBOSITY = 0  # 0 = silent, 1 = progress, 2 = debug

class AzureDevOpsOrgAPI:
    def __init__(self, organization: str):
        self.organization = organization
        self.base_url = f"https://dev.azure.com/{organization}"
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
            print("You may also need to run: az devops configure --defaults organization=https://dev.azure.com/<your-organization>", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse Azure CLI token response: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    def get_all_projects(self) -> List[Dict]:
        """Get all projects in the organization"""
        url = f"{self.base_url}/_apis/projects"
        params = {"api-version": "7.0"}
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()['value']
        except requests.RequestException as e:
            print(f"Error fetching projects: {e}", file=sys.stderr)
            return []
    
    def get_repositories(self, project_name: str) -> List[Dict]:
        """Get all repositories in a project"""
        url = f"{self.base_url}/{project_name}/_apis/git/repositories"
        params = {"api-version": "7.0"}
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()['value']
        except requests.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 404:
                    if VERBOSITY >= 2:
                        print(f"Project {project_name} not found or no access (404)", file=sys.stderr)
                elif e.response.status_code == 403:
                    if VERBOSITY >= 2:
                        print(f"Access denied to project {project_name} (403)", file=sys.stderr)
                else:
                    if VERBOSITY >= 2:
                        print(f"Error fetching repositories for project {project_name}: {e}", file=sys.stderr)
            else:
                print(f"Network error fetching repositories for project {project_name}: {e}", file=sys.stderr)
            return []
    
    def get_pull_requests(self, project_name: str, repository_id: str, skip: int = 0, top: int = 100) -> List[Dict]:
        """Get pull requests for a specific repository"""
        url = f"{self.base_url}/{project_name}/_apis/git/repositories/{repository_id}/pullrequests"
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
    
    def count_project_prs(self, project_name: str, start_date: str, end_date: str, use_creation_date: bool = False) -> int:
        """Count all pull requests in a project for the given date range"""
        repositories = self.get_repositories(project_name)
        if VERBOSITY >= 2:
            print(f"  Found {len(repositories)} repositories in project '{project_name}'", file=sys.stderr)
        
        total_pr_count = 0
        repos_with_prs = 0
        repos_skipped = 0
        
        for repo in repositories:
            repo_id = repo['id']
            repo_name = repo['name']
            
            if VERBOSITY >= 2:
                print(f"    Checking repository: {repo_name}", file=sys.stderr)
            
            skip = 0
            batch_size = 100
            repo_pr_count = 0
            repo_has_data = False
            
            while True:
                prs = self.get_pull_requests(project_name, repo_id, skip, batch_size)
                
                # Check if this is the first successful call for this repo
                if prs and not repo_has_data:
                    repo_has_data = True
                
                if not prs:
                    break
                
                # Filter PRs by date
                filtered_pr_count = 0
                for pr in prs:
                    date_field = pr['creationDate'] if use_creation_date else pr.get('closedDate')
                    
                    if date_field:
                        # Parse date and check if it's in range
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
                                print(f"      Warning: Could not parse date '{date_field}': {e}", file=sys.stderr)
                            continue
                        
                        start_dt = datetime.fromisoformat(start_date).date()
                        end_dt = datetime.fromisoformat(end_date).date()
                        
                        if start_dt <= pr_date < end_dt:
                            filtered_pr_count += 1
                
                repo_pr_count += filtered_pr_count
                
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
                    print(f"      Found {repo_pr_count} PRs in date range from {repo_name}", file=sys.stderr)
            elif not repo_has_data:
                repos_skipped += 1
            
            total_pr_count += repo_pr_count
        
        if VERBOSITY >= 2:
            print(f"  Project '{project_name}': {total_pr_count} PRs total", file=sys.stderr)
            print(f"  Repositories with PRs: {repos_with_prs}, Repositories skipped: {repos_skipped}", file=sys.stderr)
        
        return total_pr_count

def parse_arguments() -> Tuple[Optional[str], Optional[str], bool, bool]:
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
            # No arguments: current month
            return None, None, True, False
        elif len(sys.argv) == 2:
            # One argument: should be year
            arg = sys.argv[1]
            try:
                year_int = int(arg)
                if 2000 <= year_int <= 2030:
                    # It's a year: whole year
                    return arg, None, False, True
            except ValueError:
                pass
            # Invalid year
            print(f"Error: Invalid year '{arg}'. Use YYYY format (e.g., 2025)", file=sys.stderr)
            sys.exit(1)
        elif len(sys.argv) == 3:
            # Two arguments: year and month
            year, month = sys.argv[1], sys.argv[2]
            try:
                year_int = int(year)
                month_int = int(month)
                if 2000 <= year_int <= 2030 and 1 <= month_int <= 12:
                    return year, month, False, False
            except ValueError:
                pass
            # Invalid year or month
            print("Error: Invalid year or month. Use YYYY MM format (e.g., 2025 5)", file=sys.stderr)
            sys.exit(1)
        else:
            print("Usage:", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv]             # Current month", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] <YYYY>      # Whole year", file=sys.stderr)
            print(f"  {sys.argv[0]} [-v|-vv] <YYYY> <MM> # Specific month", file=sys.stderr)
            print("", file=sys.stderr)
            print("Verbosity options:", file=sys.stderr)
            print("  -v   Show progress information", file=sys.stderr)
            print("  -vv  Show detailed debug information", file=sys.stderr)
            sys.exit(1)
    finally:
        # Restore original sys.argv
        sys.argv = original_argv

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
        start_date = f"{year}-01-01"
        end_date = f"{int(year) + 1:04d}-01-01"  # Start of next year
        period_desc = f"for the year {year}"
    else:
        # Specific month and year
        start_date = f"{year}-{int(month):02d}-01"
        
        # Calculate end of month
        if int(month) == 12:
            next_month = f"{int(year) + 1:04d}-01-01"
        else:
            next_month = f"{year}-{int(month) + 1:02d}-01"
        
        end_date = next_month
        period_desc = f"for {year}-{int(month):02d}"
    
    return start_date, end_date, period_desc

def get_organization_from_azure_cli() -> str:
    """Get the Azure DevOps organization from environment or Azure CLI configuration"""
    # 1) Environment variable override
    env_org = os.environ.get("ADO_ORGANIZATION") or os.environ.get("AZURE_DEVOPS_ORGANIZATION")
    if env_org:
        return env_org.strip().rstrip('/')

    try:
        # 2) Azure DevOps CLI configuration
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
                return org_url.rstrip('/')
        
        # 3) Git remote URL as a fallback
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
                    return parts[0].rstrip('/')
        
        # If still not found, error out with guidance
        print("Error: Could not determine Azure DevOps organization.", file=sys.stderr)
        print("Please set the ADO_ORGANIZATION environment variable, or configure Azure DevOps CLI:", file=sys.stderr)
        print("  az devops configure --defaults organization=https://dev.azure.com/<your-organization>", file=sys.stderr)
        sys.exit(1)
        
    except subprocess.CalledProcessError:
        print("Error: Could not determine Azure DevOps organization.", file=sys.stderr)
        print("Please set the ADO_ORGANIZATION environment variable, or configure Azure DevOps CLI:", file=sys.stderr)
        print("  az devops configure --defaults organization=https://dev.azure.com/<your-organization>", file=sys.stderr)
        sys.exit(1)

def main():
    """Main execution function"""
    # Parse arguments
    year, month, use_current_month, use_whole_year = parse_arguments()
    
    # Get date range
    start_date, end_date, period_desc = get_date_range(year, month, use_current_month, use_whole_year)
    
    # Get organization
    organization = get_organization_from_azure_cli()
    
    if VERBOSITY >= 2:
        date_type = "creation" if USE_CREATION_DATE else "completion"
        print(f"Analyzing organization-wide PR data {period_desc}", file=sys.stderr)
        print(f"Fetching PR data between {start_date} and {end_date} (by {date_type} date)...", file=sys.stderr)
        print(f"Organization: {organization}", file=sys.stderr)
    
    try:
        # Initialize API client
        api = AzureDevOpsOrgAPI(organization)
        
        # Get all projects in the organization
        projects = api.get_all_projects()
        
        if not projects:
            print("No projects found in the organization or access denied.", file=sys.stderr)
            sys.exit(1)
        
        if VERBOSITY >= 2:
            print(f"Found {len(projects)} projects in organization '{organization}'", file=sys.stderr)
        elif VERBOSITY >= 1:
            print(f"Analyzing {len(projects)} projects in organization '{organization}'...", file=sys.stderr)
        
        # Count PRs for each project
        project_counts = {}
        total_prs = 0
        
        for i, project in enumerate(projects):
            project_name = project['name']
            
            if VERBOSITY >= 2:
                print(f"Analyzing project '{project_name}' ({i+1}/{len(projects)})...", file=sys.stderr)
            elif VERBOSITY >= 1:
                print(f"\r{i+1}/{len(projects)} projects processed", end='', file=sys.stderr)
            
            try:
                project_pr_count = api.count_project_prs(project_name, start_date, end_date, USE_CREATION_DATE)
                project_counts[project_name] = project_pr_count
                total_prs += project_pr_count
                
            except Exception as e:
                print(f"\nWarning: Failed to analyze project '{project_name}': {e}", file=sys.stderr)
                if VERBOSITY >= 2:
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                project_counts[project_name] = 0
                continue
        
        if VERBOSITY >= 1:
            print(f"\r{len(projects)}/{len(projects)} projects processed", file=sys.stderr)
        
        # Print results
        date_field_desc = "created" if USE_CREATION_DATE else "completed"
        print()
        print(f"### Organization-wide PR Count Analysis {period_desc}")
        print()
        print(f"**Total PRs {date_field_desc}: {total_prs}**")
        print()
        print("Per-project breakdown:")
        
        # Sort projects by PR count (descending)
        sorted_projects = sorted(project_counts.items(), key=lambda x: x[1], reverse=True)
        
        for project_name, count in sorted_projects:
            if count > 0 or VERBOSITY >= 2:  # Show zero counts only in verbose mode
                print(f"  {project_name}: {count} PRs")
        
        # Summary statistics
        projects_with_prs = sum(1 for count in project_counts.values() if count > 0)
        print()
        print(f"Summary:")
        print(f"  Projects analyzed: {len(projects)}")
        print(f"  Projects with PRs: {projects_with_prs}")
        print(f"  Total PR count: {total_prs}")
        
        if total_prs > 0:
            avg_prs_per_active_project = total_prs / projects_with_prs if projects_with_prs > 0 else 0
            print(f"  Average PRs per active project: {avg_prs_per_active_project:.1f}")
        
    except Exception as e:
        print(f"Error: Failed to fetch or process organization data: {e}", file=sys.stderr)
        if VERBOSITY >= 2:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()