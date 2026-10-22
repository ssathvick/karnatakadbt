import java.lang.instrument.*;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermission;
import java.security.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.asm.*;

/** Admission before Spring's scheduled invocation, including ShedLock advice.
 * Uses no application services and cannot execute business work itself.
 */
public final class NativeSchedulerGate {
    static volatile Path authority;
    static volatile Path marker;
    public static volatile boolean transformed;
    public static final AtomicLong blocked = new AtomicLong();
    static final String TARGET = "org/springframework/scheduling/support/ScheduledMethodRunnable";
    static final String PIN = "__TARGET_SHA256__";

    public static boolean allow() {
        try {
            if (authority == null || marker == null || !Files.notExists(marker, LinkOption.NOFOLLOW_LINKS)
                || !Files.isRegularFile(authority, LinkOption.NOFOLLOW_LINKS) || Files.size(authority) > 4096)
                return reject();
            Set<PosixFilePermission> mode = Files.getPosixFilePermissions(authority, LinkOption.NOFOLLOW_LINKS);
            if (mode.contains(PosixFilePermission.GROUP_WRITE) || mode.contains(PosixFilePermission.OTHERS_WRITE))
                return reject();
            Properties state = new Properties();
            try (var stream = Files.newInputStream(authority, LinkOption.NOFOLLOW_LINKS)) { state.load(stream); }
            if (!state.stringPropertyNames().equals(Set.of("owner", "generation"))
                || !"LEGACY".equals(state.getProperty("owner"))
                || !state.getProperty("generation", "").matches("[1-9][0-9]{0,17}")) return reject();
            return true;
        } catch (Exception denied) { return reject(); }
    }

    static boolean reject() { blocked.incrementAndGet(); return false; }

    public static void premain(String arguments, Instrumentation instrumentation) throws Exception {
        String[] parts = arguments == null ? new String[0] : arguments.split("\\|", -1);
        if (parts.length != 2) throw new SecurityException("Explicit scheduler admission directories required");
        Path root = Path.of(parts[0]).toRealPath();
        Path cutover = Path.of(parts[1]).toRealPath();
        if (!Files.isDirectory(root) || !Files.isDirectory(cutover)) throw new SecurityException("Admission directories unavailable");
        authority = root.resolve("authority.properties"); marker = cutover.resolve("producer-fence.json");
        instrumentation.addTransformer(new ClassFileTransformer() {
            public byte[] transform(ClassLoader loader, String name, Class<?> replaced,
                                    ProtectionDomain domain, byte[] input) {
                if (!TARGET.equals(name)) return null;
                try {
                    if (!HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input)).equals(PIN))
                        throw new SecurityException("Scheduled invocation bytecode differs from pinned retained runtime");
                    ClassReader reader = new ClassReader(input);
                    ClassWriter output = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
                    int[] matches = {0};
                    reader.accept(new ClassVisitor(Opcodes.ASM9, output) {
                        public MethodVisitor visitMethod(int access, String method, String descriptor, String signature, String[] errors) {
                            MethodVisitor delegate = super.visitMethod(access, method, descriptor, signature, errors);
                            if (!method.equals("run") || !descriptor.equals("()V")) return delegate;
                            matches[0]++;
                            return new MethodVisitor(Opcodes.ASM9, delegate) {
                                public void visitCode() {
                                    super.visitCode();
                                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "NativeSchedulerGate", "allow", "()Z", false);
                                    Label admitted = new Label();
                                    super.visitJumpInsn(Opcodes.IFNE, admitted);
                                    super.visitInsn(Opcodes.RETURN);
                                    super.visitLabel(admitted);
                                    super.visitFrame(Opcodes.F_SAME, 0, null, 0, null);
                                }
                            };
                        }
                    }, 0);
                    if (matches[0] != 1) throw new SecurityException("Exact scheduled entry point required");
                    transformed = true;
                    return output.toByteArray();
                } catch (Throwable invalid) {
                    // Transformer exceptions normally permit unmodified loading.
                    // A replacement process must terminate instead of running
                    // an unguarded scheduler. The prior JVM is never attached.
                    Runtime.getRuntime().halt(78);
                    return null;
                }
            }
        });
    }
}
