import com.sun.tools.attach.VirtualMachine;
public class NativeCertifyTrustAttach {
    public static void main(String[] args) throws Exception {
        if(args.length!=3||!args[0].matches("[0-9]+"))throw new SecurityException("Explicit retained PID required");
        VirtualMachine machine=VirtualMachine.attach(args[0]);
        try { machine.loadAgent(args[1],args[2]); } finally { machine.detach(); }
    }
}
