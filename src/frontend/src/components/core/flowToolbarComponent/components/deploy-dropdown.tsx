import IconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import useFlowsManagerStore from "@/stores/flowsManagerStore";

export default function DeployDropdown() {
  const domain = window.location.origin;
  const flowName = useFlowsManagerStore((state) => state.currentFlow?.name);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="default" className="font-medium">
          Deploy
          <IconComponent name="ChevronDown" className="icon-size font-medium" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        sideOffset={10}
        alignOffset={-10}
        align="end"
        className="min-w-[300px] max-w-[400px]"
      >
        <DropdownMenuItem className="deploy-dropdown-item text-nowrap">
          <div className="group">
            <IconComponent name="Globe" className="icon-size mr-2" />
            <a
              className="w-full truncate"
              href={`${domain}/${flowName}`}
              target="_blank"
              rel="noreferrer"
            >
              {domain.replace(/^https?:\/\//, "")}/{flowName}
            </a>
          </div>
        </DropdownMenuItem>
        <DropdownMenuItem className="deploy-dropdown-item group">
          <div>
            <IconComponent name="Code2" className="icon-size mr-2" />
            <span>API access</span>
          </div>
        </DropdownMenuItem>
        <DropdownMenuItem className="deploy-dropdown-item group">
          <div>
            <IconComponent name="Columns2" className="icon-size mr-2" />
            <span>Embed into site</span>
          </div>
        </DropdownMenuItem>
        <DropdownMenuItem className="deploy-dropdown-item group">
          <div>
            <IconComponent name="FileCode2" className="icon-size mr-2" />
            <span>Langflow SDK</span>
          </div>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
