import com.sun.tools.attach.VirtualMachine;
import com.sun.tools.attach.VirtualMachineDescriptor;
import java.util.*;

/** Runs as the existing application UID inside its own PID namespace. */
public class NativeCertifyCacheAttach {
    public static void main(String[] args) throws Exception {
        long self = ProcessHandle.current().pid();
        List<VirtualMachineDescriptor> targets = VirtualMachine.list().stream()
                .filter(v -> !v.id().equals(Long.toString(self))).toList();
        if (targets.size() != 1) throw new SecurityException("One unambiguous retained application JVM required");
        VirtualMachine machine = VirtualMachine.attach(targets.get(0).id());
        try { machine.loadAgent(args[0], args[1]); } finally { machine.detach(); }
    }
}
