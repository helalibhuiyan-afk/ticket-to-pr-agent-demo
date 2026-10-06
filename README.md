# ticket-to-pr-agent-demo

This is a demo project to showcase an agentic solution that auto processes Jira tickets and create a pull request. 
In this hypothetical demo, users will create a sample ticket in the UI. Then an agent running on the background will 
start an investigation, propose a fix, and submit a report. End user will approve the fix on the UI. Then the agent 
processes the investigation report and submits a PR. Users will be able to view the current state of each ticket and 
its associated investigation and pr. A control plane service orchestrate ticket processing. That is the scope of this demo. 

This can be further extended to add deployment responsibility to the agent that will automatically take this PR to 
production, with necessary human approval in-between.


## Architecture of this demo

### Logical architecture
There are few components in this demo system, each of which should be running in a Docker container in a single VM.
- There is a single UI that allows users to create new tickets, see the status of a ticket, investigation report, submitted PR, etc.
  - There is no authentication or login to the UI. 
  - The UI calls the control plane API to create a ticket, show context (status, investigation, pr) about tickets.
  - The control plane calls the demo service to actually create a ticket.
- A demo service that is a composition of multiple service components. The tools within the MCP gateway call these service components.
  - A fake Jira ticket service. Provides basic ticket functionality.
  - A fake log service. Provides some fake logs that will help with the ticket investigation.
  - A fake repository/pr service. To mimic creating pull requests, see diff.
  - Use a SQLLite instance as the database.
- MCP Gateway service with local tools, no authentication/authorization needed.
  - Jira MCP module, calls the Jira ticket service in the demo service.
  - Log MCP module, calls the fake log service module.
  - Repository MCP module. Calls the fake pr service.
  - Context MCP module. Calls the control plane to get context about a ticket.
- A control plane service to orchestrate ticket processing.
  - The control plane has its own SQLLite database where it stores context about tickets.
- The agent.
  - The agent takes two roles. Investigation and development.
  - Investigator agent reads the ticket, previous case history, and simulated logs through MCP tools. 
  - It reports a likely cause and proposes a fix.
  - End user approves the fix.
  - The agent takes developer role and picks up the task. It reads a small demo repository service and prepares a patch.
  - It creates a dummy PR stored inside the demo, containing the diff and description.
- A local LLM. The agent will use this local LLM. Suggest me options.
- A reverse proxy

### Call flow. 
1. User creates a ticket in UI
2. The control plane picks it up and creates a case.
3. The control plane stores a task for the agent to process the case.
4. The agent taking an investigator role, investigates the ticket, reads logs, and proposes a fix.
5. End user approves the fix in UI. Control plane persists the approval.
6. The control plane notifies the agent about the case.
7. The agent takes the developer role, reads the ticket and case context, and submits a PR.
8. End user views the status and diff of the PR in the UI.

## Physical Architecture
This demo will be hosted on a cloud-hosted Ubuntu x86 machine with 4 cores, 32Gb memory, and 100GB of boot volume. 
This machine has a public IP, accessible from the internet, and has this GitHub repo cloned.