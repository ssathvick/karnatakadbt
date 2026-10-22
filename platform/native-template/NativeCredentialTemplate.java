import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.math.BigDecimal;
import org.apache.velocity.VelocityContext;
import org.apache.velocity.app.VelocityEngine;
import org.apache.velocity.tools.generic.DateTool;
import org.apache.velocity.tools.generic.EscapeTool;

/** Data-only template process. No service implementations or credentials. */
public final class NativeCredentialTemplate {
    static int budget = 1024 * 1024;
    static String string(DataInputStream input) throws IOException {
        int size = input.readInt();
        if (size < 0 || size > budget) throw new IOException("Input bound exceeded");
        budget -= size;
        byte[] bytes = input.readNBytes(size);
        if (bytes.length != size) throw new EOFException();
        return new String(bytes, StandardCharsets.UTF_8);
    }
    static Object value(DataInputStream input, int depth) throws IOException {
        if (depth > 24) throw new IOException("Nesting bound exceeded");
        int type = input.readUnsignedByte();
        if (type == 0) return null;
        if (type == 1) return string(input);
        if (type == 2) return new BigDecimal(string(input));
        if (type == 3) return input.readBoolean();
        int count = input.readInt();
        if (count < 0 || count > 10000) throw new IOException("Collection bound exceeded");
        if (type == 4) {
            List<Object> result = new ArrayList<>();
            for (int i = 0; i < count; i++) result.add(value(input, depth + 1));
            return result;
        }
        if (type == 5) {
            Map<String,Object> result = new LinkedHashMap<>();
            for (int i = 0; i < count; i++) result.put(string(input), value(input, depth + 1));
            return result;
        }
        throw new IOException("Invalid data type");
    }
    static class BoundedWriter extends Writer {
        StringBuilder buffer = new StringBuilder();
        public void write(char[] value, int offset, int length) throws IOException {
            if (buffer.length() + length > 1024 * 1024) throw new IOException("Output bound exceeded");
            buffer.append(value, offset, length);
        }
        public void flush() {}
        public void close() {}
    }
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        DataInputStream input = new DataInputStream(System.in);
        String template = string(input);
        Map<String,Object> context = (Map<String,Object>) value(input, 0);
        if (input.read() != -1) throw new IOException("Unexpected input");
        if (java.util.regex.Pattern.compile("(?i)#\\s*(parse|include|evaluate)\\b").matcher(template).find())
            throw new IOException("Resource directives disabled");
        if (java.util.regex.Pattern.compile("\\.(getClass|forName|getClassLoader|newInstance)\\s*\\(").matcher(template).find())
            throw new IOException("Reflection directives disabled");
        VelocityEngine engine = new VelocityEngine();
        engine.setProperty("introspector.uberspect.class", "org.apache.velocity.util.introspection.SecureUberspector");
        engine.setProperty("runtime.introspector.uberspect", "org.apache.velocity.util.introspection.SecureUberspector");
        engine.setProperty("introspector.restrict.packages", "java.lang.reflect,java.io,java.nio,java.net,javax.script");
        engine.setProperty("introspector.restrict.classes", "java.lang.Class,java.lang.ClassLoader,java.lang.System,java.lang.Runtime,java.lang.ProcessBuilder,java.lang.Thread");
        engine.setProperty("directive.foreach.max_loops", 10000);
        engine.setProperty("directive.parse.max_depth", 8);
        engine.setProperty("velocimacro.max_depth", 8);
        engine.setProperty("runtime.references.strict", false);
        engine.init();
        context.put("_dateTool", new DateTool());
        context.put("_esc", new EscapeTool());
        BoundedWriter output = new BoundedWriter();
        engine.evaluate(new VelocityContext(context), output, "native-credential", template);
        System.out.write(output.buffer.toString().getBytes(StandardCharsets.UTF_8));
    }
}
