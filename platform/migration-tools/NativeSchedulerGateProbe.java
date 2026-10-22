import java.nio.file.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.scheduling.support.ScheduledMethodRunnable;

/** Calls the actual retained Spring scheduled entry point in a fresh JVM. */
public class NativeSchedulerGateProbe {
    static final AtomicInteger calls = new AtomicInteger();
    public void ownedJob() { calls.incrementAndGet(); }
    public static void main(String[] args) throws Exception {
        Path authority = Path.of(args[0]), marker = Path.of(args[1]);
        ScheduledMethodRunnable task = new ScheduledMethodRunnable(new NativeSchedulerGateProbe(),
            NativeSchedulerGateProbe.class.getMethod("ownedJob"));
        if (!NativeSchedulerGate.transformed) throw new AssertionError("Retained entry point not instrumented");
        if (args.length == 3 && args[2].equals("--expect-blocked")) {
            task.run();
            if (calls.get() != 0 || NativeSchedulerGate.allow()) throw new AssertionError("Replacement JVM admitted a fenced legacy job");
            System.out.println("{\"passed\":true,\"new_jvm_blocked\":true}");
            return;
        }
        task.run();
        if (calls.get() != 1) throw new AssertionError("Unfenced legacy owner did not run");
        Files.writeString(marker, "{}"); task.run();
        if (calls.get() != 1) throw new AssertionError("Fenced task ran");
        Files.delete(marker);
        Files.writeString(authority, "owner=NATIVE\ngeneration=2\n"); task.run();
        if (calls.get() != 1) throw new AssertionError("Legacy task ran under native owner");
        Files.writeString(authority, "owner=LEGACY\ngeneration=3\n"); task.run();
        if (calls.get() != 2) throw new AssertionError("Restored legacy task did not run");
        Files.delete(authority); task.run();
        if (calls.get() != 2) throw new AssertionError("Missing admission failed open");
        Files.writeString(authority, "owner=LEGACY\ngeneration=4\n");
        Files.createSymbolicLink(marker, marker.resolveSibling("missing-target")); task.run();
        if (calls.get() != 2) throw new AssertionError("Dangling marker failed open");
        Files.delete(marker);
        System.out.println("{\"passed\":true,\"retained_scheduled_entry_point\":true,\"checks\":6}");
    }
}
